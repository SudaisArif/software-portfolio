//
//  MotionSensorsViewModel.swift
//  SeizureDetection
//
//

import Foundation
import CoreMotion
import AVFoundation
import SwiftUI

class MotionSensorsViewModel: ObservableObject {
    
    let motionManager = CMMotionManager()
    @Published var accelerationMagnitude: Double = 0.0
    @Published var accelerationX: Double = 0.0
    @Published var accelerationY: Double = 0.0
    @Published var accelerationZ: Double = 0.0
    @Published var isAccelerometerAvailable: Bool = true
    @Published var rotationAngle: Angle = .zero
    @Published var isMonitoringFallDetection: Bool = false
    @Published var accMagnitude: Double = 0.0
    @Published var gyroMagnitude: Double = 0.0
    @Published var difference: Double = 0.0
    @Published var magMinMax: [Double] = []
    @Published var heartRateSample: Double?
    
    func startMotionUpdates() {
        if motionManager.isAccelerometerAvailable {
            isAccelerometerAvailable = true
            motionManager.accelerometerUpdateInterval = 1.0 / 500
            motionManager.gyroUpdateInterval = 1.0 / 500
            motionManager.startAccelerometerUpdates(to: .main) { data, error in
                if let deviceMotion = data {
                    self.updateAccelerationData(using: deviceMotion)
                    if (abs(deviceMotion.acceleration.x) + abs(deviceMotion.acceleration.y) + abs(deviceMotion.acceleration.z)) >= 9 {
                        if self.accelerationMagnitude > 6 {
                            self.motionManager.stopAccelerometerUpdates()
                            self.accelerationX = abs(deviceMotion.acceleration.x)
                            self.accelerationY = abs(deviceMotion.acceleration.y)
                            self.accelerationZ = abs(deviceMotion.acceleration.z)
                            var systemSoundID : SystemSoundID = 1013
                            let url = URL(fileURLWithPath: "/System/Library/Audio/UISounds/sms-received5.caf")
                            AudioServicesCreateSystemSoundID(url as CFURL, &systemSoundID)
                            AudioServicesPlaySystemSound(systemSoundID)
                            self.fetchHeartRateData()
                            self.speechSynthesizer(name: "Fall detected!, I repeat Fall detected!")
                            self.magMinMax.removeAll()
                            
                            let dateFormatter = DateFormatter()
                            dateFormatter.dateStyle = .full
                            dateFormatter.timeStyle = .medium
                            dateFormatter.timeZone = .current
                            
                            UserDefaults.standard.set(dateFormatter.string(from: Date()), forKey: "lastDetected")
                            self.isMonitoringFallDetection = false
                        }
                    }
                }
            }
        } else {
            isAccelerometerAvailable = false
        }
    }
    
    func updateAccelerationData(using data: CMAccelerometerData) {
        let x = data.acceleration.x.magnitude
        let y = data.acceleration.y.magnitude
        let z = data.acceleration.z.magnitude
        
        accelerationX = x
        accelerationY = y
        accelerationZ = z
        accelerationMagnitude = sqrt(x*x + y*y + z*z)
        magMinMax.append(accelerationMagnitude)
        
        accMagnitude = sqrt(x*x + y*y + z*z)
        
        //        let inverse = acos((simd_double3(x: x, y: y, z: z)/9.8)*180)
        if let minValue = magMinMax.min(), let maxValue = magMinMax.max() {
            let difference = maxValue - minValue
            print("\(difference), \(data.acceleration.x.magnitude)")
            self.difference = difference
            if difference >= 9 {
                //                magMinMax.removeAll()
                //                speechSynthesizer(name: "Fall detected!, I repeat Fall detected!")
            }
        } else {
            //            print("The array is empty or contains nil values.")
        }
        //        print(x,",",y,",",z,",",(magMinMax.max() - magMinMax.min()))
        //        print(inverse.max() - inverse.min())
        //        print(inverse.min())
    }
    
    
    func calculateMags(accMag: Double, gyroMag: Double) {
        
    }
    
    func speechSynthesizer(name: String) {
        let utterance = AVSpeechUtterance(string: name)
        utterance.voice = AVSpeechSynthesisVoice(language: "en-US")
        utterance.volume = 100
        utterance.rate = 0.45
        let synthesizer = AVSpeechSynthesizer()
        synthesizer.speak(utterance)
    }
    
    
    func fetchHeartRateData() {
        let manager = HeartRateManager()
        manager.requestAuthorization { success, error in
            if success {
                manager.fetchHeartRateData { sample, error in
                    DispatchQueue.main.async {
                        if let sample = sample {
                            self.heartRateSample = sample.rounded()
                            print(sample)
                        } else if let error = error {
                            print("Error fetching heart rate data: \(error.localizedDescription)")
                        }
                    }
                }
            } else if let error = error {
                print("Error requesting health kit authorization: \(error.localizedDescription)")
            }
        }
    }
}
