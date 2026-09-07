/** @file llboxxyaotransfer.h
 * @brief Inventory-based AO transfer between Boxxy, Firestorm and ZHAO-II.
 * Copyright (c) 2026 Boxxy Viewer contributors. LGPL-2.1-or-later.
 */
#ifndef LL_LLBOXXYAOTRANSFER_H
#define LL_LLBOXXYAOTRANSFER_H
#include "lluuid.h"

namespace LLBoxxyAOTransfer
{
void importFolder(const LLUUID& folder_id);
void importNotecard(const LLUUID& item_id);
void exportToFirestorm(const LLUUID& set_id);
void exportNotecard(const LLUUID& set_id);
void openImportInventory();
bool isBusy();
bool isWriting();
void update();
void cancel();
}
#endif
