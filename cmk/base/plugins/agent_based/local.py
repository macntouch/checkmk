#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (C) 2019 tribe29 GmbH - License: GNU General Public License v2
# This file is part of Checkmk (https://checkmk.com). It is subject to the terms and
# conditions defined in the file COPYING, which is part of this source code package.

# Example output from agent:
# 0 Service_FOO V=1 This Check is OK
# 1 Bar_Service - This is WARNING and has no performance data
# 2 NotGood V=120;50;100;0;1000 A critical check
# P Some_other_Service value1=10;30;50|value2=20;10:20;0:50;0;100 Result is computed from two values
# P This_is_OK foo=18;20;50
# P Some_yet_other_Service temp=40;30;50|humidity=28;50:100;0:50;0;100
# P Has-no-var - This has no variable
# P No-Text hirn=-8;-20
import shlex
import time

from typing import Dict, List, NamedTuple, Optional, Tuple, Union

import six

from .agent_based_api.v0 import check_levels, register, Service, Result, state, render, Metric

Perfdata = NamedTuple("Perfdata", [
    ("name", str),
    ("value", float),
    ("levels", Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]),
    ("tuple", Tuple[str, Optional[float], Optional[float], Optional[float], Optional[float],
                    Optional[float]]),
])

LocalResult = NamedTuple("LocalResult", [
    ("cached", Optional[Tuple[float, float, float]]),
    ("item", str),
    ("state", Union[int, str]),
    ("text", str),
    ("perfdata", List[Perfdata]),
])


def float_ignore_uom(value):
    '''16MB -> 16.0'''
    while value:
        try:
            return float(value)
        except ValueError:
            value = value[:-1]
    return 0.0


def _try_convert_to_float(value):
    try:
        return float(value)
    except ValueError:
        return None


def _parse_cache(line, now):
    """add cache info, if found"""
    if not line or not line[0].startswith("cached("):
        return None, line

    cache_raw, stripped_line = line[0], line[1:]
    creation_time, interval = (float(v) for v in cache_raw[7:-1].split(',', 1))
    age = now - creation_time

    # make sure max(..) will give the oldest/most outdated case
    return (age, 100.0 * age / interval, interval), stripped_line


def _is_valid_line(line):
    return len(line) >= 4 or (len(line) == 3 and line[0] == 'P')


def _sanitize_state(raw_state):
    try:
        raw_state = int(raw_state)
    except ValueError:
        pass
    if raw_state not in ('P', 0, 1, 2, 3):
        return 3, "Invalid plugin status %r. " % raw_state
    return raw_state, ""


def _parse_perfentry(entry):
    '''parse single perfdata entry

    return a named tuple containing check_levels compatible levels field, as well as
    cmk.base compatible perfdata 6-tuple.

    This function may raise Index- or ValueErrors.
    '''
    entry = entry.rstrip(";")
    name, raw = entry.split('=', 1)
    raw = raw.split(";")
    value = float_ignore_uom(raw[0])

    # create a check_levels compatible levels quadruple
    levels = [None] * 4
    if len(raw) >= 2:
        warn = raw[1].split(':', 1)
        levels[0] = _try_convert_to_float(warn[-1])
        if len(warn) > 1:
            levels[2] = _try_convert_to_float(warn[0])
    if len(raw) >= 3:
        crit = raw[2].split(':', 1)
        levels[1] = _try_convert_to_float(crit[-1])
        if len(crit) > 1:
            levels[3] = _try_convert_to_float(crit[0])

    # only the critical level can be set, in this case warning will be equal to critical
    if levels[0] is None and levels[1] is not None:
        levels[0] = levels[1]

    # create valid perfdata 6-tuple
    min_ = float(raw[3]) if len(raw) >= 4 else None
    max_ = float(raw[4]) if len(raw) >= 5 else None
    tuple_ = (name, value, levels[0], levels[1], min_, max_)

    # check_levels won't handle crit=None, if warn is present.
    if levels[0] is not None and levels[1] is None:
        levels[1] = float('inf')
    if levels[2] is not None and levels[3] is None:
        levels[3] = float('-inf')

    return Perfdata(name, value, (levels[0], levels[1], levels[2], levels[3]), tuple_)


def _parse_perftxt(string):
    if string == '-':
        return [], ""

    perfdata = []
    msg = []
    for entry in string.split('|'):
        try:
            perfdata.append(_parse_perfentry(entry))
        except (ValueError, IndexError):
            msg.append(entry)
    if msg:
        return perfdata, "Invalid performance data: %r. " % "|".join(msg)
    return perfdata, ""


def parse_local(string_table):
    now = time.time()
    parsed = {}  # type: Dict[Optional[str], Union[LocalResult, List]]
    for line in string_table:
        # allows blank characters in service description
        if len(line) == 1:
            # from agent version 1.7, local section with ":sep(0)"
            # In python2 shlex uses cStringIO (if available), which is not able to deal with unicode
            # strings *urgs* (See https://docs.python.org/2/library/stringio.html#module-cStringIO).
            # To workaround this, we encode/and decode for shlex.
            stripped_line = [six.ensure_text(s) for s in shlex.split(six.ensure_str(line[0]))]
        else:
            stripped_line = line

        cached, stripped_line = _parse_cache(stripped_line, now)
        if not _is_valid_line(stripped_line):
            # just pass on the line, to report the offending ouput
            parsed.setdefault(None, []).append(" ".join(stripped_line))  # type: ignore[union-attr]
            continue

        raw_state, state_msg = _sanitize_state(stripped_line[0])
        item = stripped_line[1]
        perfdata, perf_msg = _parse_perftxt(stripped_line[2])
        # convert escaped newline chars
        # (will be converted back later individually for the different cores)
        text = " ".join(stripped_line[3:]).replace("\\n", "\n")
        if state_msg or perf_msg:
            raw_state = 3
            text = "%s%sOutput is: %s" % (state_msg, perf_msg, text)
        parsed[item] = LocalResult(cached, item, raw_state, text, perfdata)

    return parsed


register.agent_section(
    name="local",
    parse_function=parse_local,
)

_STATE_FROM_INT = {
    0: state.OK,
    1: state.WARN,
    2: state.CRIT,
    3: state.UNKNOWN,
}

_SORT_FOR_BEST = {
    state.OK: 0,
    state.WARN: 1,
    state.UNKNOWN: 2,
    state.CRIT: 3,
}

_STATE_MARKERS = {
    state.OK: "",
    state.WARN: "(!)",
    state.UNKNOWN: "(?)",
    state.CRIT: "(!!)",
}


# Compute state according to warn/crit levels contained in the
# performance data.
def local_compute_state(perfdata):
    for entry in perfdata:
        yield from check_levels(
            entry.value,
            levels_upper=entry.levels[:2],
            levels_lower=entry.levels[2:],
            metric_name=entry.name,
            label=entry.name,
            boundaries=entry.tuple[-2:],
        )


def discover_local(section):
    if None in section:
        output = section[None][0]
        raise ValueError("Invalid line in agent section <<<local>>>: %r" % (output,))

    for key in section:
        yield Service(item=key)


def check_local(item, params, section):
    local_result = section.get(item)
    if local_result is None:
        return

    if local_result.state != 'P':
        yield Result(
            state=_STATE_FROM_INT[local_result.state],
            summary=local_result.text,
        )
        for perf in local_result.perfdata:
            yield Metric(perf.name, perf.value, levels=perf.levels[:2], boundaries=perf.tuple[4:6])

    else:
        if local_result.text:
            yield Result(state=state.OK, summary=local_result.text)
        yield from local_compute_state(local_result.perfdata)

    if local_result.cached is not None:
        # We try to mimic the behaviour of cached agent sections.
        # Problem here: We need this info on a per-service basis, so we cannot use the section header.
        # Solution: Just add an informative message with the same wording as in cmk/gui/plugins/views/utils.py
        infotext = "Cache generated %s ago, Cache interval: %s, Elapsed cache lifespan: %s" % (
            render.timespan(local_result.cached[0]),
            render.timespan(local_result.cached[2]),
            render.percent(local_result.cached[1]),
        )
        yield Result(state=state.OK, summary=infotext)


def cluster_check_local(item, params, section):

    # collect the result instances and yield the rest
    results_by_node = {}
    for node, node_section in section.items():
        subresults = []
        for subresult in check_local(item, {}, node_section):
            if isinstance(subresult, Result):
                subresults.append(subresult)
            else:
                yield subresult
        if subresults:
            results_by_node[node] = (state.worst(*(r.state for r in subresults)), subresults)

    if params is None or params.get("outcome_on_cluster", "worst") == "worst":
        yield from _aggregate_worst(results_by_node)
    else:
        yield from _aggregate_best(results_by_node)


def _aggregate_worst(results_by_node):

    global_worst_state = state.worst(
        *(sum_state for sum_state, _results in results_by_node.values()))

    worst_node = sorted(node for node, (sum_state, _results) in results_by_node.items()
                        if sum_state == global_worst_state)[0]

    for subr in results_by_node.pop(worst_node)[1]:
        yield Result(
            state=subr.state,
            summary="[%s]: %s" % (worst_node, subr.summary),
            details="[%s]: %s" % (worst_node, subr.details),
        )

    for node, (_sum_state, subresults) in sorted(results_by_node.items()):
        for subr in subresults:
            yield Result(
                state=subr.state,
                details="[%s]: %s" % (node, subr.summary),
            )


def _aggregate_best(results_by_node):

    global_best_state = min(
        (sum_state for sum_state, _results in results_by_node.values()),
        key=_SORT_FOR_BEST.get,
    )

    best_node = sorted(node for node, (sum_state, _results) in results_by_node.items()
                       if sum_state == global_best_state)[0]

    for subr in results_by_node.pop(best_node)[1]:
        yield Result(
            state=subr.state,
            summary="[%s]: %s" % (best_node, subr.summary),
            details="[%s]: %s" % (best_node, subr.details),
        )

    for node, (_sum_state, subresults) in sorted(results_by_node.items()):
        for subr in subresults:
            yield Result(
                state=state.OK,
                details="[%s]: %s%s" % (node, subr.details, _STATE_MARKERS[subr.state]),
            )


register.check_plugin(
    name="local",
    service_name="%s",
    discovery_function=discover_local,
    check_default_parameters={},
    check_ruleset_name="local",
    check_function=check_local,
    cluster_check_function=cluster_check_local,
)
