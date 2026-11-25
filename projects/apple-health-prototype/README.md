# Apple health prototype

Collaborative iOS/watchOS prototype from 2023, presented as a source snapshot under Sudais Arif's university GitHub account.

## Implemented in this snapshot

- SwiftUI screen showing acceleration components, monitoring state and the last detection time.
- Core Motion accelerometer sampling and a threshold-based alert with sound/speech.
- HealthKit authorization and a query for a heart-rate sample within the preceding ten minutes.
- A watchOS `CMFallDetectionManager` authorization flow and fall-event delegate callback.

The watch UI remains a starter view; its event handler logs detections. This snapshot does not implement a verified end-to-end watch-to-phone alert pipeline, emergency-contact messaging or seizure prediction. The heart-rate query is not a trained seizure model. It is a development prototype, not a medical device.

## Open

Open `SeizureDetection.xcodeproj` in Xcode, select your own signing team and review the iOS/watchOS targets and capabilities. Real sensor and HealthKit testing requires compatible devices and permissions. No health records or credentials are bundled. Original signing-team identifiers and per-developer Xcode state were removed from this distribution. A device build has not been verified for this portfolio.

The project was collaborative; this repository does not assert sole authorship. Name/date creation headers were removed for presentation; no license or copyright notice was removed.
