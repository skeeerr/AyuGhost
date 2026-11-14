# SPDX-License-Identifier: GPL-3.0-only
# AyuGhost: modified source version, 2026-11-14.
# AyuGhost changes maintained by @internetmodel and @skerbio.
# Original feature basis: re:extera by @bleizix and @shikaatux.
# See LICENSE and NOTICE for licensing and attribution.

"""Hooks call only classes already present in exteraGram. No external class loader."""
import math
import time
import threading
from collections import OrderedDict
from java import jclass, dynamic_proxy
from base_plugin import MethodHook
from hook_utils import find_class,get_private_field,set_private_field
from policy import READING,TYPING,STORIES,OUTGOING,request_action,silent_mode

Runnable=jclass('java.lang.Runnable')
class Task(dynamic_proxy(Runnable)):
    def __init__(self,callback):super().__init__();self.callback=callback
    def run(self):self.callback()

def name(obj):
    return str(obj.getClass().getSimpleName()) if obj is not None else ''
def field(obj,key,default=None):
    if obj is None:return default
    try:return getattr(obj,key)
    except Exception:
        value=get_private_field(obj,key)
        return default if value is None else value

def put(obj,key,value):
    try:setattr(obj,key,value)
    except Exception:
        if not set_private_field(obj,key,value):raise AttributeError(key)

def seq(obj):
    if obj is None:return []
    try:return list(obj)
    except TypeError:return [obj.get(i) for i in range(obj.size())]

def java_list(items):
    result=jclass('java.util.ArrayList')()
    for item in items:result.add(item)
    return result

def account(obj=None):
    value=field(obj,'currentAccount')
    if value is None:
        try:return int(obj.getCurrentAccount())
        except Exception:return int(jclass('org.telegram.messenger.UserConfig').selectedAccount)
    return int(value)

def dialog(message):
    try:return int(message.getDialogId())
    except Exception:
        owner=field(message,'messageOwner',message)
        did=int(field(owner,'dialog_id',0))
        if did:return did
        peer=field(owner,'peer_id')
        return int(field(peer,'user_id',0)) or -int(field(peer,'channel_id',0)) or -int(field(peer,'chat_id',0))

def message_id(obj):
    try:return int(obj.getId())
    except Exception:return int(field(field(obj,'messageOwner',obj),'id',0))

def serialize(message):
    stream=jclass('org.telegram.tgnet.SerializedData')()
    try:
        message.serializeToStream(stream)
        return bytes(int(b)&255 for b in stream.toByteArray())
    finally:stream.cleanup()

def deserialize(data):
    stream=jclass('org.telegram.tgnet.SerializedData')(data)
    try:return jclass('org.telegram.tgnet.TLRPC$Message').TLdeserialize(stream,stream.readInt32(False),False)
    finally:stream.cleanup()

class Callback(MethodHook):
    def __init__(self,owner,before=None,after=None):
        super().__init__();self.owner=owner;self.before=before;self.after=after
    def before_hooked_method(self,param):
        if self.before and self.owner.active:self.owner.protected(self.before,param)
    def after_hooked_method(self,param):
        if self.after and self.owner.active:self.owner.protected(self.after,param)

class Native:
    def __init__(self,plugin):
        self.p=plugin;self.active=True;self.handles=[];self.failures=[];self.callbacks=[]
        self.errors={};self.bypass={};self.unfiltered=set();self.last_offline={}
        self.filter_patterns=[];self.lock=threading.RLock();self.suppress_until=0
        self.refresh_filters()
    def protected(self,fn,param):
        try:fn(param)
        except Exception as e:
            label=fn.__name__;now=time.monotonic()
            if now-self.errors.get(label,-60)>=30:
                self.errors[label]=now;self.p.log('AyuGhost '+label+': '+str(e))
    def hook(self,clazz,method,before=None,after=None,counts=None):
        try:
            c=find_class(clazz)
            if c is None:
                self.failures.append(clazz+'.'+method+': class missing');return
            # Chaquopy exposes Java types as Python classes. Reflection belongs
            # to their java.lang.Class object, obtained with getClass().
            reflected=c.getClass() if isinstance(c,type) else c
            methods=reflected.getDeclaredMethods()
        except Exception as e:
            self.failures.append(clazz+'.'+method+': reflection failed: '+str(e));return
        callback=Callback(self,before,after);matched=0
        for m in methods:
            if str(m.getName())!=method:continue
            if counts is not None and len(m.getParameterTypes()) not in counts:continue
            try:
                m.setAccessible(True);h=self.p.hook_method(m,callback)
                if h is not None:self.handles.append(h);matched+=1
            except Exception as e:self.failures.append(clazz+'.'+method+': '+str(e))
        if matched:self.callbacks.append(callback)
        else:self.failures.append(clazz+'.'+method+': matching method missing')
    def start(self):
        # All targets and overload guards are visible to the scanner and reviewer.
        self.hook('org.telegram.tgnet.ConnectionsManager','sendRequestInternal',self.request,self.request_after,counts={10})
        self.hook('org.telegram.messenger.MessagesStorage','markMessagesAsDeletedInternal',self.storage_delete,counts={5})
        self.hook('org.telegram.messenger.MessagesController','deleteMessages',self.manual_delete,counts={7})
        self.hook('org.telegram.ui.ChatActivity','processDeletedMessages',self.chat_delete,counts={4})
        self.hook('org.telegram.messenger.NotificationsController','removeDeletedMessagesFromNotifications',self.notifications_delete,counts={2})
        self.hook('org.telegram.messenger.MessagesController','processUpdateArray',self.capture_edits,counts={5})
        self.hook('org.telegram.ui.ChatActivity','processNewMessages',self.chat_messages,counts={4})
        self.hook('org.telegram.ui.ChatActivity','didReceivedNotification',self.loaded_messages,counts={3})
        self.hook('org.telegram.ui.Cells.ChatMessageCell','measureTime',after=self.measure_time,counts={1})
        self.hook('org.telegram.ui.Cells.ChatMessageCell','setMessageObject',after=self.cell_alpha)
        self.hook('org.telegram.messenger.MessagesController','checkDeletingTask',self.no_expiry,counts={1})
        self.hook('org.telegram.ui.SecretVoicePlayer','dismiss',self.voice_dismiss)
        self.hook('org.telegram.ui.ChatActivity','sendSecretMediaDelete',self.secret_delete,counts={1})
        self.hook('org.telegram.ui.ChatActivity','sendSecretMessageRead',self.secret_read,counts={1})
        self.hook('org.telegram.messenger.MessagesController','isChatNoForwards',self.allow_forwards,counts={1})
        self.hook('org.telegram.messenger.MessagesController','isUserNoForwards',self.allow_forwards,counts={1})
        self.hook('org.telegram.messenger.MessageObject','canForwardMessage',self.can_forward,counts={0})
        self.hook('org.telegram.ui.ChatActivity','hasSelectedNoforwardsMessage',self.allow_forwards,counts={0})
        self.hook('org.telegram.messenger.SendMessagesHelper','sendMessage',self.send_message,counts={1})
        self.hook('org.telegram.ui.ChatActivity','openScheduledMessages',self.scheduled_open,counts={2})
        self.hook('org.telegram.messenger.MessagesController','getDialogs',after=self.dialogs_result,counts={1})
        self.hook('org.telegram.ui.DialogsActivity','getDialogsArray',after=self.dialogs_result)
        self.hook('org.telegram.messenger.MessagesController','processLoadedDialogs',self.loaded_dialogs)
        self.hook('org.telegram.messenger.NotificationsController','processNewMessages',self.filter_notifications)
        self.hook('org.telegram.ui.Cells.DialogCell','buildLayout',self.dialog_preview,counts={0})
        self.hook('org.telegram.messenger.UserConfig','isPremium',self.local_premium,counts={0})
        self.hook('android.view.Window','setFlags',self.window_flags,counts={2})
        self.hook('android.view.WindowManagerImpl','addView',self.add_window,counts={2})
        self.hook('org.telegram.messenger.FlagSecureReason','attach',self.secure_attach)
    def stop(self):
        self.active=False
        for h in reversed(self.handles):
            try:self.p.unhook_method(h)
            except Exception as e:self.p.log('AyuGhost unhook: '+str(e))
        self.handles.clear();self.callbacks.clear();self.bypass.clear();self.unfiltered.clear()
    def enabled(self,key):return bool(self.p.option(key))
    def refresh_filters(self):
        Pattern=jclass('java.util.regex.Pattern');patterns=[]
        for value in self.p.archive.filters:
            try:patterns.append(Pattern.compile(value))
            except Exception as e:self.p.log('AyuGhost invalid saved filter: '+str(e))
        self.filter_patterns=patterns
    def request_dialog(self,r):
        peer=field(r,'peer')
        if peer is not None:
            user=int(field(peer,'user_id',0));channel=int(field(peer,'channel_id',0));chat=int(field(peer,'chat_id',0))
            if user:return user
            if channel:return -channel
            if chat:return -chat
        channel=field(r,'channel')
        if channel:return -int(field(channel,'channel_id',0))
        from client_utils import get_last_fragment
        f=get_last_fragment()
        try:return int(f.getDialogId())
        except Exception:return 0
    def request(self,param):
        if not len(param.args):return
        r=param.args[0];tag=name(r);a=account(param.thisObject)
        # Manually requested reads bypass the privacy rule only during this synchronous call.
        if r is None or int(r.hashCode()) in self.unfiltered:return
        did=self.request_dialog(r);reading,typing=self.p.archive.exception(did)
        action=request_action(tag,self.enabled('ghostEnabled'),self.p.option,reading,typing)
        if action=='offline':put(r,'offline',True)
        elif action=='cancel':param.setResult(None);return
        if tag in OUTGOING and self.enabled('ghostEnabled'):
            if self.enabled('readOnInteract') and did:self.mark_read(a,did,int(field(r,'reply_to_msg_id',0)))
    def request_after(self,param):
        if not (self.enabled('ghostEnabled') and self.enabled('immediateOffline')):return
        r=param.args[0]
        if r is None or name(r) not in OUTGOING:return
        a=account(param.thisObject);now=time.monotonic()
        if now-self.last_offline.get(a,0)>2:
            self.last_offline[a]=now
            request=jclass('org.telegram.tgnet.tl.TL_account$updateStatus')();request.offline=True
            self.send_request(a,request)
    def send_request(self,a,request):
        # The request is created locally and sent through Telegram's own connection.
        controller=jclass('org.telegram.tgnet.ConnectionsManager').getInstance(int(a))
        token=int(request.hashCode());self.unfiltered.add(token)
        try:controller.sendRequest(request,None)
        finally:self.unfiltered.discard(token)
    def mark_read(self,a,did,mid=0):
        controller=jclass('org.telegram.messenger.MessagesController').getInstance(int(a))
        if not mid:
            f=controller.dialogs_dict.get(int(did))
            mid=int(field(f,'top_message',0))
        if mid<=0:return
        if int(did)<0:
            chat=controller.getChat(-int(did))
            if bool(field(chat,'broadcast',False)) or bool(field(chat,'megagroup',False)):
                r=jclass('org.telegram.tgnet.TLRPC$TL_channels_readHistory')();r.channel=controller.getInputChannel(-int(did))
            else:r=jclass('org.telegram.tgnet.TLRPC$TL_messages_readHistory')();r.peer=controller.getInputPeer(int(did))
        else:r=jclass('org.telegram.tgnet.TLRPC$TL_messages_readHistory')();r.peer=controller.getInputPeer(int(did))
        r.max_id=int(mid);self.send_request(a,r)
    def remember(self,obj,a,edited=False):
        owner=field(obj,'messageOwner',obj);did=dialog(obj);mid=message_id(obj)
        if not did or mid<=0:return
        if not (self.enabled('saveDeleted') or self.enabled('saveEdits')):return
        self.p.archive.snapshot(a,did,mid,int(field(owner,'date',0)),str(field(owner,'message','') or ''),serialize(owner),edited)
    def storage_messages(self,storage,did,mids):
        if not mids:return []
        numbers=','.join(str(int(mid)) for mid in mids)
        scope='uid = '+str(int(did)) if did else 'is_channel = 0'
        sql='SELECT uid,mid,data FROM messages_v2 WHERE mid IN('+numbers+') AND '+scope
        cur=storage.getDatabase().queryFinalized(sql,[]);result=[]
        try:
            while cur.next():
                buffer=cur.byteBufferValue(2)
                if buffer is None:continue
                try:
                    message=jclass('org.telegram.tgnet.TLRPC$Message').TLdeserialize(buffer,buffer.readInt32(False),False)
                    if message is not None:
                        message.dialog_id=cur.longValue(0);result.append(message)
                finally:buffer.reuse()
        finally:cur.dispose()
        return result
    def storage_delete(self,param):
        if not self.enabled('saveDeleted') or int(param.args[3])!=0:return
        did=int(param.args[0]);mids=seq(param.args[1]);keep=[];archive=[];a=account(param.thisObject)
        now=time.monotonic()
        for mid in mids:
            key=(a,did,int(mid));allowed=self.bypass.get(key,0)>now
            if int(mid)<=0 or allowed:keep.append(mid)
            else:archive.append(mid)
        if not archive:return
        for message in self.storage_messages(param.thisObject,did,archive):
            actual=dialog(message);self.remember(message,a)
            self.p.archive.mark(a,actual,[message_id(message)])
        if keep:param.args[1]=java_list(keep)
        else:param.setResult(None)
        self.refresh(a)
    def manual_delete(self,param):
        if not self.enabled('saveDeleted') or int(param.args[6])!=0:return
        did=int(param.args[3]);a=account(param.thisObject)
        if self.enabled('saveManuallyDeleted'):return
        deadline=time.monotonic()+30
        self.bypass={k:v for k,v in self.bypass.items() if v>time.monotonic()}
        for mid in seq(param.args[0]):self.bypass[(a,did,int(mid))]=deadline
    def chat_delete(self,param):
        if not self.enabled('saveDeleted') or int(param.thisObject.getChatMode())!=0:return
        did=int(param.thisObject.getDialogId());a=account(param.thisObject);now=time.monotonic()
        keep=[m for m in seq(param.args[0]) if int(m)<=0 or self.bypass.get((a,did,int(m)),0)>now]
        param.args[0]=java_list(keep)
    def notifications_delete(self,param):
        if self.enabled('saveDeleted'):param.setResult(None)
    def capture_edits(self,param):
        if not self.enabled('saveEdits'):return
        a=account(param.thisObject);storage=jclass('org.telegram.messenger.MessagesStorage').getInstance(a)
        for update in seq(param.args[0]):
            if name(update) not in ('TL_updateEditMessage','TL_updateEditChannelMessage'):continue
            message=field(update,'message')
            if message is None or bool(field(message,'out',False)):continue
            def capture(message=message):
                if not self.active:return
                try:
                    previous=self.storage_messages(storage,dialog(message),[message_id(message)])
                    if previous:self.remember(previous[0],a)
                    self.remember(message,a,edited=True)
                except Exception as e:self.p.log('AyuGhost edit capture: '+str(e))
            storage.getStorageQueue().postRunnable(Task(capture))
    def hidden_message(self,obj):
        if bool(field(field(obj,'messageOwner',obj),'out',False)):return False
        did=dialog(obj)
        try:sender=int(obj.getFromChatId())
        except Exception:sender=int(field(field(field(obj,'messageOwner',obj),'from_id'),'user_id',0))
        hidden=self.p.archive.hidden.get(sender,(False,False))
        if (did<0 and hidden[1]) or (did>0 and hidden[0]):return True
        if self.enabled('filtersEnabled'):
            text=str(field(field(obj,'messageOwner',obj),'message','') or '')
            return any(pattern.matcher(text).find() for pattern in self.filter_patterns)
        return False
    def chat_messages(self,param):
        a=account(param.thisObject);messages=seq(param.args[0])
        for obj in messages:self.remember(obj,a)
        param.args[0]=java_list([obj for obj in messages if not self.hidden_message(obj)])
    def loaded_messages(self,param):
        center=jclass('org.telegram.messenger.NotificationCenter')
        if int(param.args[0])!=int(center.messagesDidLoad):return
        args=param.args[2]
        if len(args)<3:return
        messages=args[2];a=int(param.args[1])
        for obj in seq(messages):self.remember(obj,a)
        kept=[m for m in seq(messages) if not self.hidden_message(m)]
        messages.clear();messages.addAll(java_list(kept))
    def measure_time(self,param):
        obj=param.args[0];cell=param.thisObject
        if not self.p.archive.is_deleted(dialog(obj),message_id(obj)):return
        current=str(field(cell,'currentTimeString','') or '')
        mark=str(self.p.option('deletedMark'))
        if mark and not current.endswith(' · '+mark):
            text=current+' · '+mark
            styled=jclass('android.text.SpannableStringBuilder')(text)
            if self.enabled('redDeletedMark'):
                Theme=jclass('org.telegram.ui.ActionBar.Theme')
                color=cell.getThemedColor(Theme.key_color_red)
                span=jclass('android.text.style.ForegroundColorSpan')(color)
                styled.setSpan(span,len(current)+3,len(text),33)
            put(cell,'currentTimeString',styled)
            paint=jclass('org.telegram.ui.ActionBar.Theme').chat_timePaint
            width=int(math.ceil(paint.measureText(text)))
            old=int(field(cell,'timeTextWidth',0))
            put(cell,'timeTextWidth',width)
            put(cell,'timeWidth',int(field(cell,'timeWidth',0))+width-old)
    def cell_alpha(self,param):
        obj=param.args[0]
        alpha=.55 if self.enabled('translucentDeleted') and self.p.archive.is_deleted(dialog(obj),message_id(obj)) else 1.0
        param.thisObject.setTransitionAlpha(alpha)
    def no_expiry(self,param):
        if self.enabled('saveOneTime'):param.setResult(False)
    def voice_dismiss(self,param):
        if self.enabled('saveOneTime'):put(param.thisObject,'closeAction',None)
    def secret_delete(self,param):
        if self.enabled('saveOneTime'):
            put(param.args[0],'forceExpired',False);param.setResult(Task(lambda:None))
    def secret_read(self,param):
        if self.enabled('saveOneTime'):param.setResult(Task(lambda:None))
    def allow_forwards(self,param):
        if self.enabled('noForwards'):param.setResult(False)
    def can_forward(self,param):
        if self.enabled('noForwards'):param.setResult(True)
    def send_message(self,param):
        params=param.args[0]
        if params is None:return
        if silent_mode(self.p.option('sendSilenceValue'),self.enabled('ghostEnabled')):put(params,'notify',False)
        if self.enabled('useSchedule') and not int(field(params,'scheduleDate',0)):
            did=int(field(params,'peer',0))
            if did and did&0xffffffff:
                size=int(field(field(params,'document'),'size',0))
                delay=12+(max(6,int(math.ceil(size/(1024*1024)*4.5))) if size else 0)
                now=jclass('org.telegram.tgnet.ConnectionsManager').getInstance(account(param.thisObject)).getCurrentTime()
                put(params,'scheduleDate',int(now)+delay);self.suppress_until=time.monotonic()+1
        # Convert an unavailable reply to an explicit quote, never drop the outgoing text.
        reply=field(params,'replyToMsg')
        if reply is not None and self.p.archive.is_deleted(dialog(reply),message_id(reply)):
            quote=str(field(reply,'messageText','') or '')
            if quote and field(params,'message') is not None:
                put(params,'message','> '+quote.replace('\n','\n> ')+'\n\n'+str(params.message))
                put(params,'replyToMsg',None)
    def scheduled_open(self,param):
        if time.monotonic()<self.suppress_until:param.setResult(None)
    def dialogs_result(self,param):
        result=param.getResult()
        if result is None:return
        for i in range(result.size()-1,-1,-1):
            did=int(field(result.get(i),'id',0))
            if self.p.archive.hidden.get(did,(False,False))[0]:result.remove(i)
    def loaded_dialogs(self,param):
        if not len(param.args):return
        result=field(param.args[0],'dialogs')
        if result is not None:
            for i in range(result.size()-1,-1,-1):
                if self.p.archive.hidden.get(int(field(result.get(i),'id',0)),(False,False))[0]:result.remove(i)
    def filter_notifications(self,param):
        if not len(param.args) or not self.p.archive.hidden:return
        param.args[0]=java_list([obj for obj in seq(param.args[0]) if not self.hidden_message(obj)])
    def dialog_preview(self,param):
        obj=field(param.thisObject,'message')
        if obj is not None and self.hidden_message(obj):
            put(obj,'messageText','Скрыто фильтром AyuGhost');put(obj,'messageTextShort',None)
            if field(obj,'caption') is not None:put(obj,'caption','Скрыто фильтром AyuGhost')
    def local_premium(self,param):
        if self.enabled('localPremium'):param.setResult(True)
    def window_flags(self,param):
        if self.enabled('ignoreFlagSecure'):param.args[0]=int(param.args[0])&~8192
    def add_window(self,param):
        if self.enabled('ignoreFlagSecure'):
            lp=param.args[1];put(lp,'flags',int(field(lp,'flags',0))&~8192)
    def secure_attach(self,param):
        if self.enabled('ignoreFlagSecure'):param.setResult(None)
    def refresh(self,a):
        center=jclass('org.telegram.messenger.NotificationCenter')
        def update():center.getInstance(int(a)).postNotificationName(center.dialogsNeedReload,[])
        jclass('org.telegram.messenger.AndroidUtilities').runOnUIThread(Task(update))
