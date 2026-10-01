"""Exercise production notification close and Delete All paths. Requires g++."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'indra/newview/llfloaternotificationstabbed.cpp').read_text()


def function(signature):
    start = source.index(signature)
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


harness = r'''
#include <cassert>
#include <map>
#include <memory>
#include <string>
#include <vector>
#include <functional>
using LLUUID=int;
struct Notification {bool im=false,form=false;
    bool canLogToIM(){return im;} bool hasFormElements(){return form;}};
using LLNotificationPtr=std::shared_ptr<Notification>;
struct LLNotifications {
    std::map<int,LLNotificationPtr> notifications; int cancellations=0; std::function<void(int)> onCancel;
    static LLNotifications& instance(){static LLNotifications registry; return registry;}
    LLNotificationPtr find(int id){auto it=notifications.find(id);return it==notifications.end()?nullptr:it->second;}
    void cancel(LLNotificationPtr notification){
        for(auto it=notifications.begin();it!=notifications.end();++it) if(it->second==notification){
            int id=it->first; notifications.erase(it); ++cancellations; if(onCancel) onCancel(id); return;
        }
        assert(false);
    }
};
struct LLPanel {virtual ~LLPanel()=default;};
struct LLNotificationListItem:LLPanel {
    int id; bool removed=false; LLNotificationListItem(int value):id(value){}
    int getID(){assert(!removed);return id;}
    std::string getNotificationName(){assert(!removed);return "MusicStreamError";}
};
struct Channel {std::function<void(int)> kill; void killToastByNotificationID(int id){if(kill)kill(id);}};
struct LLFloaterNotificationsTabbed {
    Channel* mChannel=nullptr; std::vector<LLPanel*> rows; int removals=0;
    void onItemClose(LLNotificationListItem*); void closeAllOnCurrentTab();
    void clearScreenChannels(){} void getAllItemsOnCurrentTab(std::vector<LLPanel*>& items){items=rows;}
    LLPanel* findItemByID(int id,std::string){for(auto* row:rows){auto* item=static_cast<LLNotificationListItem*>(row); if(item->id==id&&!item->removed)return row;}return nullptr;}
    void removeItemByID(int id,std::string name){auto* item=static_cast<LLNotificationListItem*>(findItemByID(id,name)); assert(item); item->removed=true; ++removals;}
};
'''
for signature in ['void LLFloaterNotificationsTabbed::onItemClose(', 'void LLFloaterNotificationsTabbed::closeAllOnCurrentTab(']:
    harness += function(signature) + '\n'
harness += r'''
int main(){
    auto& registry=LLNotifications::instance();
    for(bool channel_present:{false,true}) for(bool toast_present:{false,true})
    for(bool notification_present:{false,true}) for(bool callback_removes_row:{false,true})
    for(bool im:{false,true}) for(bool form:{false,true}) {
        LLFloaterNotificationsTabbed window; Channel channel; LLNotificationListItem item(1); window.rows={&item};
        window.mChannel=channel_present?&channel:nullptr;
        registry.notifications.clear(); registry.cancellations=0;
        if(notification_present){auto n=std::make_shared<Notification>();n->im=im;n->form=form;registry.notifications[1]=n;}
        registry.onCancel=[&](int id){if(callback_removes_row)window.removeItemByID(id,"MusicStreamError");};
        channel.kill=[&](int id){auto n=registry.find(id);if(toast_present&&n&&(!im||!form))registry.cancel(n);};
        window.onItemClose(&item);
        assert(item.removed&&window.removals==1);
        assert(registry.cancellations==(notification_present&&(!im||!form)?1:0));
        assert(bool(registry.find(1))==(notification_present&&im&&form));
    }
    LLFloaterNotificationsTabbed window; Channel channel; window.mChannel=&channel;
    LLNotificationListItem live(1),stale(2); window.rows={&live,&stale};
    registry.notifications.clear(); registry.notifications[1]=std::make_shared<Notification>();
    registry.onCancel=[&](int id){window.removeItemByID(id,"MusicStreamError");};
    window.closeAllOnCurrentTab(); assert(live.removed&&stale.removed&&window.removals==2);
}
'''
with tempfile.TemporaryDirectory() as directory:
    cpp, binary = Path(directory) / 'check.cpp', Path(directory) / 'check.exe'
    cpp.write_text(harness)
    subprocess.run(['g++', '-std=c++17', str(cpp), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print('X and Delete All: live/stale toasts, cancellation callbacks and IM-form protections passed.')
