// +------------------------------------------------------------------+
// |             ____ _               _        __  __ _  __           |
// |            / ___| |__   ___  ___| | __   |  \/  | |/ /           |
// |           | |   | '_ \ / _ \/ __| |/ /   | |\/| | ' /            |
// |           | |___| | | |  __/ (__|   <    | |  | | . \            |
// |            \____|_| |_|\___|\___|_|\_\___|_|  |_|_|\_\           |
// |                                                                  |
// | Copyright Mathias Kettner 2014             mk@mathias-kettner.de |
// +------------------------------------------------------------------+
//
// This file is part of Check_MK.
// The official homepage is at http://mathias-kettner.de/check_mk.
//
// check_mk is free software;  you can redistribute it and/or modify it
// under the  terms of the  GNU General Public License  as published by
// the Free Software Foundation in version 2.  check_mk is  distributed
// in the hope that it will be useful, but WITHOUT ANY WARRANTY;  with-
// out even the implied warranty of  MERCHANTABILITY  or  FITNESS FOR A
// PARTICULAR PURPOSE. See the  GNU General Public License for more de-
// tails. You should have  received  a copy of the  GNU  General Public
// License along with GNU Make; see the file  COPYING.  If  not,  write
// to the Free Software Foundation, Inc., 51 Franklin St,  Fifth Floor,
// Boston, MA 02110-1301 USA.

#include "AndingFilter.h"
#include <algorithm>
#include <memory>
#include <vector>
#include "Filter.h"
#include "FilterVisitor.h"
#include "OringFilter.h"
#include "Row.h"

void AndingFilter::accept(FilterVisitor &v) const { v.visit(*this); }

bool AndingFilter::accepts(Row row, const contact *auth_user,
                           std::chrono::seconds timezone_offset) const {
    for (const auto &filter : _subfilters) {
        if (!filter->accepts(row, auth_user, timezone_offset)) {
            return false;
        }
    }
    return true;
}

void AndingFilter::findIntLimits(const std::string &colum_nname, int *lower,
                                 int *upper,
                                 std::chrono::seconds timezone_offset) const {
    for (const auto &filter : _subfilters) {
        filter->findIntLimits(colum_nname, lower, upper, timezone_offset);
    }
}

bool AndingFilter::optimizeBitmask(const std::string &column_name,
                                   uint32_t *mask,
                                   std::chrono::seconds timezone_offset) const {
    bool optimized = false;
    for (const auto &filter : _subfilters) {
        if (filter->optimizeBitmask(column_name, mask, timezone_offset)) {
            optimized = true;
        }
    }
    return optimized;
}

std::unique_ptr<Filter> AndingFilter::copy() const {
    auto af = std::make_unique<AndingFilter>();
    for (const auto &sf : _subfilters) {
        af->addSubfilter(sf->copy());
    }
    return af;
}

std::unique_ptr<Filter> AndingFilter::negate() const {
    auto af = std::make_unique<OringFilter>();
    for (const auto &sf : _subfilters) {
        af->addSubfilter(sf->negate());
    }
    return af;
}

const std::string *AndingFilter::findValueForIndexing(
    const std::string &column_name) const {
    for (const auto &filter : _subfilters) {
        if (auto value = filter->valueForIndexing(column_name)) {
            return value;
        }
    }
    return nullptr;
}

std::unique_ptr<Filter> AndingFilter::stealLastSubFilter() {
    if (_subfilters.empty()) {
        return nullptr;
    }
    std::unique_ptr<Filter> l = move(_subfilters.back());
    _subfilters.pop_back();
    return l;
}

void AndingFilter::combineFilters(int count, LogicalOperator andor) {
    auto variadic = VariadicFilter::make(andor);
    for (auto i = 0; i < count; ++i) {
        variadic->addSubfilter(std::move(_subfilters.back()));
        _subfilters.pop_back();
    }
    addSubfilter(std::move(variadic));
}
