# SPDX-License-Identifier: GPL-3.0-only
# AyuGhost: modified source version, 2026-11-14.
# AyuGhost changes maintained by @internetmodel and @skerbio.
# Original feature basis: re:extera by @bleizix and @shikaatux.
# See LICENSE and NOTICE for licensing and attribution.

"""AyuGhost source port. All plugin logic ships as reviewable Python files."""
import os
import sqlite3
import time
from base_plugin import BasePlugin,MenuItemData,MenuItemType
from java import jclass
from client_utils import get_last_fragment
from ui.settings import Text,Header,Divider,Switch,Selector,Input
from ui.alert import AlertDialogBuilder
from policy import DEFAULTS
from storage import Archive
from native import Native,field,put,account,dialog,message_id,deserialize,Task

# This preview has its own identity and data copy; it cannot replace the working DEX build.
__id__='ayughost_source_test'
__name__='AyuGhost · Source Test'
__version__='1.0'
__icon__='pfsdpsfdpsdfpfsd_by_fStikBot/2'
LEGACY={'ghostEnabled':'ghost_mode_enabled','hideOnline':'hide_online','immediateOffline':'immediate_offline','hideTyping':'hide_typing','hideReading':'hide_reading','noReadStories':'no_read_stories','readOnInteract':'read_on_interact','useSchedule':'use_schedule','ghostMenuButton':'add_ghost_to_drawer','sendSilenceValue':'send_silence','saveDeleted':'save_deleted_messages','saveManuallyDeleted':'save_manually_deleted','saveOneTime':'save_one_time_messages','saveEdits':'save_edited_messages','redDeletedMark':'red_mark','translucentDeleted':'translucent_deleted','deletedMark':'custom_prefix','localPremium':'local_premium','noForwards':'no_forward','ignoreFlagSecure':'remove_flag_secure','filtersEnabled':'filters_enabled'}

class Plugin(BasePlugin):
    def __init__(self):
        super().__init__();self.native=None;self.archive=None;self.preferences=None
        self.menu_ids=[];self.last_filters_error=None
    def log_error(self,label,error):self.log('AyuGhost '+label+': '+str(error))
    def option(self,key):return self.get_setting(key,DEFAULTS.get(key))
    def on_plugin_load(self):
        context=jclass('org.telegram.messenger.ApplicationLoader').applicationContext
        self.preferences=context.getSharedPreferences('ayughost',0)
        directory=str(context.getFilesDir().getAbsolutePath())
        # The test port works on a SQLite backup, keeping the working version untouched.
        legacy_path=os.path.join(directory,'ayughost.db')
        self.path=os.path.join(directory,'ayughost_source_test.db')
        if not os.path.exists(self.path) and os.path.isfile(legacy_path):
            src=sqlite3.connect('file:'+legacy_path+'?mode=ro',uri=True)
            dst=sqlite3.connect(self.path)
            try:src.backup(dst)
            finally:dst.close();src.close()
        self.archive=Archive(self.path)
        self.import_legacy_settings()
        self.native=Native(self)
        try:self.native.start();self.add_menus()
        except Exception:
            self.on_plugin_unload();raise
        if self.native.failures:self.log('AyuGhost unavailable hooks: '+'; '.join(self.native.failures))
    def import_legacy_settings(self):
        if super().get_setting('source_settings_imported',False):return
        for key,old in LEGACY.items():
            default=DEFAULTS[key]
            if not self.preferences.contains(old):continue
            if isinstance(default,bool):value=self.preferences.getBoolean(old,default)
            elif isinstance(default,int):value=self.preferences.getInt(old,default)
            else:value=str(self.preferences.getString(old,default))
            super().set_setting(key,value,reload_settings=False)
        super().set_setting('source_settings_imported',True,reload_settings=False)
    def on_plugin_unload(self):
        if self.native:self.native.stop();self.native=None
        for mid in self.menu_ids:
            try:self.remove_menu_item(mid)
            except Exception as e:self.log_error('menu unload',e)
        self.menu_ids=[]
        if self.archive:self.archive.close();self.archive=None
    def get_setting(self,key,default=None):
        if key.startswith('exception:') and self.archive:
            _,which,did=key.split(':');values=self.archive.exception(int(did));return values[int(which)]
        return super().get_setting(key,default)
    def set_setting(self,key,value,reload_settings=False):
        if key.startswith('exception:') and self.archive:
            _,which,did=key.split(':');old=list(self.archive.exception(int(did)));old[int(which)]=int(value)
            self.archive.set_exception(int(did),*old)
            return
        super().set_setting(key,value,reload_settings=reload_settings)
        if key=='filtersText' and self.archive:
            patterns=[x.strip() for x in str(value).splitlines() if x.strip()]
            Pattern=jclass('java.util.regex.Pattern')
            try:
                for pattern in patterns:Pattern.compile(pattern)
            except Exception as e:
                self.last_filters_error=str(e);self.notice('Ошибка фильтра',str(e));return
            self.last_filters_error=None;self.archive.set_filters(patterns)
            if self.native:self.native.refresh_filters()
        if key=='ghostEnabled' and value and self.option('immediateOffline') and self.native:
            r=jclass('org.telegram.tgnet.tl.TL_account$updateStatus')();r.offline=True
            self.native.send_request(account(),r)
    def create_settings(self):
        return [Text(text='Режим призрака',subtext='Онлайн, прочтения, набор текста и исключения',icon='ghost',create_sub_fragment=self.ghost_settings),
                Text(text='Архив сообщений',subtext='Удалённые, история правок и исчезающие медиа',icon='menu_hide_gift',create_sub_fragment=self.archive_settings),
                Text(text='Инструменты и фильтры',subtext='Фильтры, локальное скрытие, пересылка и диагностика',icon='msg_list',create_sub_fragment=self.tools_settings)]
    def switch(self,key,title,description):return Switch(key=key,text=title,subtext=description,default=DEFAULTS[key])
    def ghost_settings(self):
        return [self.switch('ghostEnabled','Режим призрака','Включает выбранные ниже способы скрытия активности.'),
                self.switch('hideOnline','Скрывать онлайн','Вместо статуса «в сети» отправляет статус «не в сети».'),
                self.switch('immediateOffline','Сразу уходить в офлайн','Обновляет статус при включении призрака и после исходящих действий.'),
                self.switch('hideTyping','Скрывать набор текста','Не отправляет индикаторы набора текста и действий в чате.'),
                self.switch('hideReading','Скрывать прочтение','Не отправляет отметки о прочтении сообщений.'),
                self.switch('noReadStories','Скрывать просмотр историй','Не отправляет просмотр историй и увеличение счётчика просмотров.'),
                self.switch('readOnInteract','Читать при взаимодействии','При ответе, реакции или отправке сообщения отмечает чат прочитанным.'),
                self.switch('ghostMenuButton','Кнопка в меню','Показывает переключатель AyuGhost в главном меню и боковой панели.'),
                self.switch('useSchedule','Отправлять через отложенные','Сообщение отправится с небольшой задержкой, которую требует сервер Telegram.'),
                Selector(key='sendSilenceValue',text='Отправка без звука',default=0,items=['Никогда','С режимом призрака','Всегда']),
                Divider(text='Управляет звуковым уведомлением получателю. Не отключает саму доставку.'),
                Text(text='Исключения для чатов',subtext='Отдельные правила прочтения и набора по ID чата.',create_sub_fragment=self.exception_list)]
    def archive_settings(self):
        return [self.switch('saveDeleted','Сохранять удалённые','Не удаляет доступные клиенту сообщения после удаления собеседником.'),
                self.switch('saveManuallyDeleted','Сохранять удалённые мной','Также сохраняет сообщения, которые ты удаляешь сам.'),
                self.switch('saveOneTime','Сохранять исчезающие медиа','Отключает локальные задачи удаления доступных одноразовых медиа.'),
                self.switch('saveEdits','История изменений','Сохраняет предыдущую и новую полученные версии текста.'),
                self.switch('redDeletedMark','Красная метка удаления','Выделяет метку удалённого сообщения красным.'),
                self.switch('translucentDeleted','Полупрозрачные удалённые','Приглушает сохранённые удалённые сообщения в чате.'),
                Input(key='deletedMark',text='Метка удаления',default='deleted',subtext='Текст рядом со временем удалённого сообщения.'),
                Text(text='Открыть локальный архив',subtext='Последние 100 сохранённых удалённых сообщений текущего аккаунта.',on_click=lambda view:self.show_deleted()),
                Text(text='Очистить архив тестовой сборки',subtext='Удаляет только копию архива Source Test после подтверждения.',red=True,on_click=lambda view:self.confirm_clear())]
    def tools_settings(self):
        return [self.switch('filtersEnabled','Фильтры сообщений','Применяет регулярные выражения к тексту входящих сообщений.'),
                Input(key='filtersText',text='Регулярные выражения',default='\n'.join(self.archive.filters) if self.archive else '',subtext='Одно выражение на строку. При ошибке старые правила сохраняются.'),
                Text(text='Локально скрытые пользователи',subtext='Скрытие диалога и сообщений пользователя в группах.',create_sub_fragment=self.hidden_settings),
                self.switch('noForwards','Разрешить действия с контентом','Снимает локальные ограничения меню. Серверные ограничения могут сохраниться.'),
                self.switch('localPremium','Локальный Premium','Меняет интерфейс клиента. Серверную подписку Telegram Premium не выдаёт.'),
                self.switch('ignoreFlagSecure','Разрешить скриншоты','Снимает FLAG_SECURE с окон этого клиента.'),
                Text(text='Диагностика',subtext='Какие перехваты установлены и какие недоступны в этой версии клиента.',on_click=lambda view:self.show_diagnostics()),
                Text(text='Отключить перехваты',subtext='Останавливает функции до повторного включения плагина.',red=True,on_click=lambda view:self.stop_hooks())]
    def selected_dialog(self):
        f=get_last_fragment()
        try:return int(f.getDialogId())
        except Exception:return int(self.get_setting('editDialogId','0') or 0)
    def exception_list(self):
        rows=[Input(key='editDialogId',text='ID чата',default='0',subtext='ID пользователя положительный, ID группы или канала отрицательный.'),
              Text(text='Настроить выбранный ID',subtext='Для чата из поля выше.',create_sub_fragment=lambda:self.exception_settings(int(self.get_setting('editDialogId','0') or 0)))]
        if self.archive:
            for did in sorted(self.archive.exceptions):rows.append(Text(text=str(did),create_sub_fragment=lambda did=did:self.exception_settings(did)))
        return rows
    def exception_settings(self,did):
        if not did:return [Divider(text='Сначала укажи ненулевой ID чата.')]
        return [Header(text='Чат '+str(did)),Selector(key=f'exception:0:{did}',text='Прочтение',default=0,items=['Общие настройки','Всегда отправлять','Не отправлять']),
                Divider(text='Исключение действует для этого чата независимо от общего переключателя.'),
                Selector(key=f'exception:1:{did}',text='Набор текста',default=0,items=['Общие настройки','Всегда отправлять','Не отправлять'])]
    def hidden_settings(self):
        rows=[Input(key='hiddenUserId',text='ID пользователя',default='0',subtext='Положительный числовой Telegram ID.'),
              Text(text='Скрыть пользователя',subtext='Скрывает диалог и его сообщения в группах локально.',on_click=lambda view:self.hide_user())]
        if self.archive:
            for uid,flags in sorted(self.archive.hidden.items()):
                rows.append(Text(text=str(uid),subtext='Нажми, чтобы вернуть отображение.',on_click=lambda view,uid=uid:self.unhide_user(uid)))
        return rows
    def notice(self,title,message):
        f=get_last_fragment()
        if f is None:return
        b=AlertDialogBuilder(f.getParentActivity());b.set_title(title);b.set_message(str(message));b.set_positive_button('Понятно',lambda d,w:d.dismiss());b.show()
    def show_deleted(self,did=None):
        if not self.archive:return
        rows=self.archive.list_deleted(account(),did)
        text='\n\n'.join(f'Чат {d}, сообщение {m}\n{body or "[медиа без подписи]"}' for d,m,date,body in rows)
        self.notice('Архив AyuGhost',text or 'В этой копии пока нет текстовых снимков. Старые сохранённые сообщения остаются в истории чатов.')
    def show_history(self,ctx):
        obj=ctx.get('message')
        if obj is None:return
        a=int(ctx.get('account',account()));did=dialog(obj);mid=message_id(obj)
        rows=self.archive.history(a,did,mid);texts=[f'{time.strftime("%d.%m %H:%M",time.localtime(date))}\n{text or "[медиа]"}' for date,text,data in rows]
        if not texts:
            for date,data in self.archive.legacy_history(did,mid):
                try:texts.append(str(field(deserialize(data),'message','[медиа]')))
                except Exception as e:self.log_error('legacy history',e)
        self.notice('История правок','\n\n'.join(texts) or 'Сохранённых правок пока нет.')
    def show_diagnostics(self):
        if self.native is None:self.notice('AyuGhost','Перехваты выключены.');return
        self.notice('Диагностика',f'Установлено перехватов: {len(self.native.handles)}\n\n'+('\n'.join(self.native.failures) or 'Ошибок регистрации нет. Проверка на устройстве всё равно необходима.'))
    def confirm_clear(self):
        f=get_last_fragment()
        if f is None:return
        b=AlertDialogBuilder(f.getParentActivity());b.set_title('Очистить тестовый архив?');b.set_message('Снимки удалённых и история правок Source Test будут удалены. Рабочая версия AyuGhost не затрагивается.')
        def clear(d,w):self.archive.clear_archive();d.dismiss()
        b.set_positive_button('Очистить',clear);b.set_negative_button('Отмена',lambda d,w:d.dismiss());b.show()
    def stop_hooks(self):
        if self.native:self.native.stop()
        self.notice('AyuGhost','Перехваты остановлены. Для запуска выключи и включи плагин.')
    def toggle_ghost(self,ctx):
        self.set_setting('ghostEnabled',not bool(self.option('ghostEnabled')),reload_settings=True)
        self.notice('AyuGhost','Призрак включён' if self.option('ghostEnabled') else 'Призрак выключен')
    def hide_user(self,ctx=None):
        uid=int(self.get_setting('hiddenUserId','0') or 0)
        if ctx:
            user=ctx.get('user');uid=int(field(user,'id',ctx.get('userId',0)))
        if uid<=0:self.notice('AyuGhost','Укажи положительный ID пользователя.');return
        self.archive.set_hidden(uid);self.native.refresh(int((ctx or {}).get('account',account())))
        self.notice('AyuGhost','Пользователь скрыт локально.')
    def unhide_user(self,uid):
        self.archive.remove_hidden(uid);self.native.refresh(account());self.notice('AyuGhost','Пользователь снова виден.')
    def read_message(self,ctx):
        obj=ctx.get('message')
        if obj is not None:self.native.mark_read(int(ctx.get('account',account())),dialog(obj),message_id(obj))
    def add_menus(self):
        specs=[(MenuItemType.MESSAGE_CONTEXT_MENU,'История правок',self.show_history,'msg_edit'),
               (MenuItemType.MESSAGE_CONTEXT_MENU,'Отметить прочитанным',self.read_message,'msg_checks'),
               (MenuItemType.CHAT_ACTION_MENU,'Архив AyuGhost',lambda ctx:self.show_deleted(int(ctx.get('dialog_id',0)) or None),'msg_list'),
               (MenuItemType.PROFILE_ACTION_MENU,'Скрыть локально',self.hide_user,'msg_block')]
        if self.option('ghostMenuButton'):
            specs.extend([(MenuItemType.MAIN_MENU,'Переключить призрака',self.toggle_ghost,'ghost'),(MenuItemType.DRAWER_MENU,'Переключить призрака',self.toggle_ghost,'ghost')])
        for kind,title,callback,icon in specs:
            self.menu_ids.append(self.add_menu_item(MenuItemData(menu_type=kind,text=title,on_click=callback,icon=icon)))
