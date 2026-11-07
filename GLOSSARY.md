# PyWarscape Sound

A modding tool for Total War: Attila and Total War: Rome II that lets modders browse game sounds and music, replace them with custom audio files, and export a working mod pack without needing to know how the game's internal audio engine works.

## Language

### What plays

**Trigger**:
Something the game fires by name when a moment happens in play, such as a unit being selected or a battle starting.
_Avoid_: Event ID, CAkEvent, dialogue event

**Play Condition**:
The game situation that decides which branch plays under a Trigger, such as a culture, a surface type, or a battle intensity level.
_Avoid_: Switch value, state key, decision tree path

**Rotation**:
A pool of Sound Slots from which the game picks one each time, at random or in order.
_Avoid_: RanSeqCntr, playlist container, variation container

**Sound Slot**:
A single playable sound or music track that a modder can listen to and replace with their own audio file.
_Avoid_: HIRC node, CAkSound, CAkMusicTrack, leaf node, target

**Recording**:
The actual audio file a Sound Slot plays.
_Avoid_: WEM, media entry, DIDX entry, source ID

**Shared Audio**:
When more than one Sound Slot plays the same Recording, possibly in different banks.
_Avoid_: WEM reference, blast radius, source_id collision

**Bank Group**:
A top-level category in the bank list (such as Music & Movies, Campaign & UI, Battle SFX, Battle Voice Orders, or Raw Audio Data Banks) that organizes the 126 game banks by their role.
_Avoid_: HIRC-only bank, DIDX/DATA bank, stub bank

### What a modder does

**Isolated Replacement**:
Giving one Sound Slot a new Recording while every other Sound Slot that shared the old Recording keeps it.
_Avoid_: Forked WEM, isolate scope

**Shared Replacement**:
Changing a Shared Audio Recording so that every Sound Slot using it plays the new audio.
_Avoid_: Overwrite scope, global replace

### Boundaries

**Audio-Only Limit**:
The rule that a mod pack can change how existing Triggers and Play Conditions sound, but cannot make the game fire new ones.
_Avoid_: Movie pack restriction, db limitation
