/**
 * @file llposerlink.h
 * Copyright (C) 2026 Prism Viewer contributors.
 * SPDX-License-Identifier: LGPL-2.1-only
 */
#ifndef LL_LLPOSERLINK_H
#define LL_LLPOSERLINK_H

namespace LLPoserLink
{
void update();
void shutdown();
void disconnect();
bool isLinked();
}

#endif
