# SPDX-License-Identifier: GPL-3.0-only
# AyuGhost: modified source version, 2026-11-14.
# AyuGhost changes maintained by @internetmodel and @skerbio.
# Original feature basis: re:extera by @bleizix and @shikaatux.
# See LICENSE and NOTICE for licensing and attribution.

"""Side-effect-free privacy rules. No downloaded or generated executable code."""
READING = frozenset(('TL_messages_readHistory','TL_messages_readEncryptedHistory','TL_messages_readDiscussion','TL_channels_readHistory','TL_messages_markDialogUnread','TL_messages_readMessageContents','TL_channels_readMessageContents'))
TYPING = frozenset(('TL_messages_setTyping','TL_messages_setEncryptedTyping'))
STORIES = frozenset(('TL_stories_readStories','TL_stories_incrementStoryViews'))
OUTGOING = frozenset(('TL_messages_sendMessage','TL_messages_sendMedia','TL_messages_sendMultiMedia','TL_messages_sendInlineBotResult','TL_messages_sendEncrypted','TL_messages_sendEncryptedFile','TL_messages_sendEncryptedMultiMedia','TL_messages_sendEncryptedService','TL_messages_sendReaction','TL_messages_forwardMessages','TL_messages_editMessage'))
DEFAULTS = {'ghostEnabled':False,'hideOnline':True,'immediateOffline':False,'hideTyping':True,'hideReading':True,'noReadStories':True,'readOnInteract':False,'useSchedule':False,'ghostMenuButton':True,'sendSilenceValue':0,'saveDeleted':False,'saveManuallyDeleted':False,'saveOneTime':False,'saveEdits':False,'redDeletedMark':False,'translucentDeleted':False,'deletedMark':'deleted','localPremium':False,'noForwards':False,'ignoreFlagSecure':False,'filtersEnabled':False}

def request_action(name, enabled, settings, exception_reading=0, exception_typing=0):
    """Return pass, offline or cancel. Exception 1 allows, 2 blocks, 0 follows global."""
    if name in ('updateStatus','TL_account_updateStatus'):
        return 'offline' if enabled and settings('hideOnline') else 'pass'
    if name in READING:
        block = exception_reading == 2 or (exception_reading == 0 and enabled and settings('hideReading'))
        return 'cancel' if block else 'pass'
    if name in TYPING:
        block = exception_typing == 2 or (exception_typing == 0 and enabled and settings('hideTyping'))
        return 'cancel' if block else 'pass'
    if name in STORIES and enabled and settings('noReadStories'):
        return 'cancel'
    return 'pass'

def silent_mode(mode, ghost):
    return int(mode) == 2 or (int(mode) == 1 and ghost)
