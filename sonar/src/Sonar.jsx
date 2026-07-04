// Sonar — responsive shell. Calls the shared useSonar hook once (one source of
// truth: layers, playlist, player, audio) and renders either the mobile
// (map-first, bottom-sheet) or desktop (landscape map+list+rails) view based on
// viewport width. The single <audio> element lives here so playback survives a
// breakpoint switch (e.g. rotating a tablet or resizing the window).
//
// Search model: each vibe / similar / dissimilar query is its own *layer* with
// its own color. Layers coexist on the map and in the list; every dot is colored
// by the search it came from. The 2D positions come from each track's x,y (a PCA
// projection of the MERT v_mid embedding — the same embedding used for
// interpolation). All of that logic lives in ./useSonar.js.
import React from 'react';
import { useSonar, useIsMobile } from './useSonar.js';
import SonarDesktop from './SonarDesktop.jsx';
import SonarMobile from './SonarMobile.jsx';
import { Toasts, HintsOverlay } from './sonar-utils.jsx';

export default function Sonar({ initialView = 'map' }) {
  const isMobile = useIsMobile();
  const s = useSonar({ initialView });

  return (
    <>
      <audio
        ref={s.audioRef}
        onTimeUpdate={s.onAudioTimeUpdate}
        onLoadedMetadata={s.onAudioLoadedMetadata}
        onEnded={s.onAudioEnded}
        onPause={s.onAudioPause}
        onPlay={s.onAudioPlay}
        onError={s.onAudioError}
      />
      {isMobile ? <SonarMobile s={s} /> : <SonarDesktop s={s} />}
      {/* Error toasts + the gesture-hints overlay live in the shell so both
          views share one instance (and they survive a breakpoint switch). */}
      <Toasts toasts={s.toasts} onDismiss={s.dismissToast} />
      {s.hintsOpen && <HintsOverlay mobile={isMobile} onClose={s.closeHints} />}
    </>
  );
}
