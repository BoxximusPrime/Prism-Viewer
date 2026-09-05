/**
 * @file llfloatereconomylog.h
 * @brief Session log of successful L$ transactions.
 */

#ifndef LL_LLFLOATERECONOMYLOG_H
#define LL_LLFLOATERECONOMYLOG_H

#include "llfloater.h"
#include "lldate.h"

#include <vector>

class LLFlatListView;
class LLMoneyLogRow;

class LLFloaterEconomyLog final : public LLFloater
{
    friend class LLMoneyLogRow;

public:
    LLFloaterEconomyLog(const LLSD& key);

    bool postBuild() override;
    void onOpen(const LLSD& key) override;
    void draw() override;

    static U32 getGeneration();
    static void addTransaction(bool outgoing,
                               S32 amount,
                               const std::string& display_name,
                               const std::string& username,
                               const std::string& detail,
                               const LLDate& timestamp,
                               U32 generation);

private:
    struct Entry
    {
        bool mOutgoing;
        S32 mAmount;
        std::string mDisplayName;
        std::string mUsername;
        std::string mDetail;
        LLDate mTimestamp;
    };

    void clearLog();
    void refresh();
    void refreshTimes();
    static std::string relativeTime(const LLDate& timestamp);

    LLFlatListView* mTransactionList = nullptr;
    std::vector<LLMoneyLogRow*> mRows;
    F64 mLastTimeRefresh = 0.0;

    static std::vector<Entry> sEntries;
    static U32 sGeneration;
};

#endif
