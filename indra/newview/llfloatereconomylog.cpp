/**
 * @file llfloatereconomylog.cpp
 * @brief Session log of successful L$ transactions.
 */

#include "llviewerprecompiledheaders.h"

#include "llfloatereconomylog.h"

#include "llbutton.h"
#include "llflatlistview.h"
#include "llfloaterreg.h"
#include "lltextbox.h"
#include "lluicolortable.h"

class LLMoneyLogRow final : public LLPanel
{
public:
    LLMoneyLogRow(bool outgoing,
                  S32 amount,
                  const std::string& display_name,
                  const std::string& username,
                  const std::string& detail,
                  const LLDate& timestamp)
    : LLPanel(),
      mTimestamp(timestamp)
    {
        buildFromFile("panel_money_log_row.xml");
        setTransparentColor(LLUIColorTable::instance().getColor(
            outgoing ? "MoneyLogDebitBgColor" : "MoneyLogCreditBgColor"));

        getChild<LLTextBox>("transaction")->setValue(outgoing
            ? llformat("- L$%d to %s", amount, display_name.c_str())
            : llformat("+ L$%d from %s", amount, display_name.c_str()));
        getChild<LLTextBox>("username")->setValue(detail.empty()
            ? username
            : username + "  -  " + detail);
        getChild<LLTextBox>("date")->setValue(timestamp.toLocalDateString("%m/%d/%Y"));
        refreshTime();
    }

    void refreshTime()
    {
        getChild<LLTextBox>("relative_time")->setValue(
            LLFloaterEconomyLog::relativeTime(mTimestamp));
    }

private:
    LLDate mTimestamp;
};

std::vector<LLFloaterEconomyLog::Entry> LLFloaterEconomyLog::sEntries;
U32 LLFloaterEconomyLog::sGeneration = 0;

LLFloaterEconomyLog::LLFloaterEconomyLog(const LLSD& key)
: LLFloater(key)
{
}

bool LLFloaterEconomyLog::postBuild()
{
    mTransactionList = getChild<LLFlatListView>("transactions");
    mTransactionList->setAllowSelection(false);
    getChild<LLButton>("clear_btn")->setClickedCallback(
        boost::bind(&LLFloaterEconomyLog::clearLog, this));
    refresh();
    return true;
}

void LLFloaterEconomyLog::onOpen(const LLSD& key)
{
    refresh();
}

void LLFloaterEconomyLog::draw()
{
    const F64 now = LLDate::now().secondsSinceEpoch();
    if (now - mLastTimeRefresh >= 1.0)
    {
        refreshTimes();
        mLastTimeRefresh = now;
    }
    LLFloater::draw();
}

U32 LLFloaterEconomyLog::getGeneration()
{
    return sGeneration;
}

void LLFloaterEconomyLog::addTransaction(bool outgoing,
                                         S32 amount,
                                         const std::string& display_name,
                                         const std::string& username,
                                         const std::string& detail,
                                         const LLDate& timestamp,
                                         U32 generation)
{
    if (generation != sGeneration)
    {
        return;
    }

    sEntries.push_back({ outgoing, amount, display_name, username, detail, timestamp });
    if (LLFloaterEconomyLog* floater =
            LLFloaterReg::findTypedInstance<LLFloaterEconomyLog>("money_log"))
    {
        floater->refresh();
    }
}

void LLFloaterEconomyLog::clearLog()
{
    sEntries.clear();
    ++sGeneration;
    refresh();
}

void LLFloaterEconomyLog::refresh()
{
    if (!mTransactionList)
    {
        return;
    }

    mTransactionList->clear();
    mRows.clear();

    for (auto entry = sEntries.rbegin(); entry != sEntries.rend(); ++entry)
    {
        LLMoneyLogRow* row = new LLMoneyLogRow(entry->mOutgoing,
            entry->mAmount, entry->mDisplayName, entry->mUsername,
            entry->mDetail, entry->mTimestamp);
        mRows.push_back(row);
        mTransactionList->addItem(row, LLSD(static_cast<S32>(mRows.size())));
    }
    mLastTimeRefresh = LLDate::now().secondsSinceEpoch();
}

void LLFloaterEconomyLog::refreshTimes()
{
    if (!mTransactionList)
    {
        return;
    }

    for (LLMoneyLogRow* row : mRows)
    {
        row->refreshTime();
    }
}

std::string LLFloaterEconomyLog::relativeTime(const LLDate& timestamp)
{
    S32 count = llmax(0, static_cast<S32>(
        LLDate::now().secondsSinceEpoch() - timestamp.secondsSinceEpoch()));
    const char* unit = "second";
    if (count >= 86400)
    {
        count /= 86400;
        unit = "day";
    }
    else if (count >= 3600)
    {
        count /= 3600;
        unit = "hour";
    }
    else if (count >= 60)
    {
        count /= 60;
        unit = "minute";
    }
    return llformat("%d %s%s ago", count, unit, count == 1 ? "" : "s");
}
