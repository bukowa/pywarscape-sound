# src/ui/features/audio_transport
Audio transport and waveform auditioning feature slice.
Provides real-time audio playback, seeking, volume adjustment, and playback status for SoundBank nodes and loose files.
- `causation.py`: Pure state transition reducer (`reconcile_transport`) handling play, pause, seek, and loop events.
- `store.py`: Headless `AudioTransportStore` managing audio decoding, playback via `pygame.mixer`, and playback progress polling.
- `structs.py`: Immutable domain ontology (`TransportState`, `AudioTrack`, `PlaybackStatus`, events, and effect intents).
- `view.py`: `AudioTransportBar` and `ClickableSlider` PySide6 controls providing scrubbable playback and volume sliders.
