//
//  ContentView.swift
//  SeizureDetectionWA Watch App
//
//

import SwiftUI
import CoreMotion

struct ContentView: View {
    
    let fallDetectionManager = FallDetectionManager()
    
    var body: some View {
        VStack {
            Image(systemName: "globe")
                .imageScale(.large)
                .foregroundColor(.accentColor)
            Text("Hello, world!")
        }
        .padding()
    }
}

struct ContentView_Previews: PreviewProvider {
    static var previews: some View {
        ContentView()
    }
}

class FallDetectionManager: NSObject, CMFallDetectionDelegate {
    
    let fallDetectionManager = CMFallDetectionManager()
    
    override init() {
        super.init()
        
        fallDetectionManager.delegate = self
        fallDetectionManager.requestAuthorization { status in
            switch status {
                
            case .notDetermined:
                print("notDetermined")
            case .restricted:
                print("restricted")
            case .denied:
                print("denied")
            case .authorized:
                print("authorized")
            @unknown default:
                print("unknown")
            }
        }
    }
    
    func fallDetectionManager(_ fallDetectionManager: CMFallDetectionManager, didDetect event: CMFallDetectionEvent) async {
        // notify on iPhone
        print("fall detected!")
    }
}
