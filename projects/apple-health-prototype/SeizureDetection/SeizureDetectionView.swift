//
//  ContentView.swift
//  SeizureDetection
//
//

import SwiftUI
import HealthKit

struct SeizureDetectionView: View {
    
    @ObservedObject var motionSensorVM = MotionSensorsViewModel()
    
    var body: some View {
        ScrollView(.vertical, showsIndicators: true) {
            VStack {
                
                Text("Fall Detection Demo")
                    .font(.title)
                    .bold()
                    .padding()
                
                if motionSensorVM.isAccelerometerAvailable {
                    
                    Image("exampleBackground")
                        .resizable()
                        .frame(width: 130, height: 130, alignment: .center)
                        .aspectRatio(contentMode: .fill)
                        .rotationEffect(motionSensorVM.rotationAngle)
                    
                    Text("Highest Acceleration")
                        .bold()
                        .padding()
                    
                    VStack(spacing: 8) {
                        Text("X = \(motionSensorVM.accelerationX, specifier: "%.5f")")
                            .bold()
                        
                        Text("Y = \(motionSensorVM.accelerationY, specifier: "%.5f")")
                            .bold()
                        
                        Text("Z = \(motionSensorVM.accelerationZ, specifier: "%.5f")")
                            .bold()
                    }
                } else {
                    Text("Accelerometer not available")
                        .font(.subheadline)
                        .bold()
                        .foregroundColor(.red)
                        .padding()
                }
                
                if motionSensorVM.heartRateSample != nil {
                    Text("Heart rate 10 mins ago \(String(format: "%.1f", motionSensorVM.heartRateSample!)) bpm")
                        .padding(.vertical, 8)
                        .foregroundColor(.red)
                        .multilineTextAlignment(.center)
                }
//                else {
//                    Text("No heart rate data available in the last 10 minutes")
//                        .padding(.vertical, 10)
//                        .foregroundColor(.brown)
//                        .multilineTextAlignment(.center)
//                }
                
                if let lastDetected = UserDefaults.standard.string(forKey: "lastDetected") {
                    Text("Last Fall Detected On\n\(lastDetected.description)")
                        .padding(.vertical)
                        .foregroundColor(.brown)
                        .multilineTextAlignment(.center)
                }
                
                Text("\(motionSensorVM.accelerationMagnitude)")
                
                Spacer()
                
                VStack(spacing: 20) {
                    
                    if motionSensorVM.isMonitoringFallDetection {
                        Text("Fall detection monitoring in process...")
                            .foregroundColor(Color(.gray))
                        
                        Button {
                            motionSensorVM.motionManager.stopAccelerometerUpdates()
                            motionSensorVM.isMonitoringFallDetection = false
                            motionSensorVM.magMinMax.removeAll()
                        } label: {
                            Text("Stop Monitoring")
                                .bold()
                                .padding(10)
                                .padding(.horizontal, 50)
                        }
                        .buttonStyle(.borderedProminent)
                        .accentColor(.red)
                    } else {
                        Button {
                            motionSensorVM.startMotionUpdates()
                            motionSensorVM.isMonitoringFallDetection = true
                        } label: {
                            Text("Start Monitoring")
                                .bold()
                                .padding(10)
                                .padding(.horizontal, 50)
                        }
                        .buttonStyle(.borderedProminent)
                    }
                    Spacer()
                }
                
            }
            .onAppear {
                let dateFormatter = DateFormatter()
                dateFormatter.dateStyle = .full
                dateFormatter.timeStyle = .medium
                dateFormatter.timeZone = .current
                UserDefaults.standard.set(dateFormatter.string(from: Date()), forKey: "lastDetected")
            }
        }
    }
}


struct SeizureDetectionView_Previews: PreviewProvider {
    static var previews: some View {
        SeizureDetectionView()
    }
}



//                        motionManager.startDeviceMotionUpdates(to: .main) { data, error in
//                            if let deviceMotion = data {
//                                self.updateGyroScopeData(using: deviceMotion)

//                                self.updateGyroScopeData(using: deviceMotion)
//                                if deviceMotion.userAcceleration.x > 9
//                                    || deviceMotion.userAcceleration.y > 9
//                                    || deviceMotion.userAcceleration.z > 9 {
//                                    motionManager.stopAccelerometerUpdates()
//                                    accelerationX = deviceMotion.userAcceleration.x
//                                    accelerationY = deviceMotion.userAcceleration.y
//                                    accelerationZ = deviceMotion.userAcceleration.z
////                                    print(deviceMotion.userAcceleration.x, ",",  deviceMotion.userAcceleration.y, ",", deviceMotion.userAcceleration.z)
////                                    deviceMotion.
//
//                                    var systemSoundID : SystemSoundID = 1013
//                                    let url = URL(fileURLWithPath: "/System/Library/Audio/UISounds/sms-received5.caf")
//                                    AudioServicesCreateSystemSoundID(url as CFURL, &systemSoundID)
//                                    AudioServicesPlaySystemSound(systemSoundID)
//
//                                    speechSynthesizer(name: "Fall detected!, I repeat Fall detected!")
//
//                                    let dateFormatter = DateFormatter()
//                                    dateFormatter.dateStyle = .full
//                                    dateFormatter.timeStyle = .medium
//                                    dateFormatter.timeZone = .current
//
//                                    UserDefaults.standard.set(dateFormatter.string(from: Date()), forKey: "lastDetected")
//                                    isMonitoringFallDetection = false
//                                }
//                            }
//                        }


//    func updateGyroScopeData(using data: CMDeviceMotion) {
//        let attitude = data.attitude
//
//        let rotationAngleX = attitude.roll
//        let rotationAngleY = attitude.pitch
//        let rotationAngleZ = attitude.yaw
//
////        let x = data.gravity.x
////        let y = data.gravity.y
////        let z = data.gravity.z
//
////        accelerationX = x
////        accelerationY = y
////        accelerationZ = z
////
////        accelerationMagnitude = sqrt(x*x + y*y + z*z)
//
//        gyroMagnitude = sqrt(rotationAngleX*rotationAngleX + rotationAngleY*rotationAngleY + rotationAngleZ*rotationAngleZ)
//
//
//
//
//        //        self.rotationAngleX = rotationAngleX
//        //        self.rotationAngleY = rotationAngleY
//        //        self.rotationAngleZ = rotationAngleZ
//
//        let rotationAngle = Angle(radians: rotationAngleZ)
//
//        DispatchQueue.main.async {
//            self.rotationAngle = rotationAngle
//        }
//    }





//                    Text("Acceleration Magnitude: \(accelerationMagnitude, specifier: "%.2f")")
//                        .font(.subheadline)
//                        .padding()
//
//                    Text("Rotation Angle X: \(rotationAngleX, specifier: "%.2f")")
//                        .font(.subheadline)
//                        .padding()
//
//                    Text("Rotation Angle Y: \(rotationAngleY, specifier: "%.2f")")
//                        .font(.subheadline)
//                        .padding()
//
//                    Text("Rotation Angle Z: \(rotationAngleZ, specifier: "%.2f")")
//                        .font(.subheadline)
//                        .padding()
