// Copyright (C) 2019 tribe29 GmbH - License: GNU General Public License v2
// This file is part of Checkmk (https://checkmk.com). It is subject to the
// terms and conditions defined in the file COPYING, which is part of this
// source code package.

#include "DynamicServiceRRDColumn.h"

#include "Column.h"
#include "ServiceRRDColumn.h"

std::unique_ptr<Column> DynamicServiceRRDColumn::createColumn(
    const std::string &name, const std::string &arguments) {
    const auto args = parse_args(arguments);
    return std::make_unique<ServiceRRDColumn>(
        name, "dynamic column", _offsets, core(), args.rpn, args.start_time,
        args.end_time, args.resolution, args.max_entries);
}
