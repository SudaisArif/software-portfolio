//
//  HealthKitManager.swift
//  SeizureDetection
//
//

import Foundation
import HealthKit

class HeartRateManager {
    let healthStore = HKHealthStore()
    
    func requestAuthorization(completion: @escaping (Bool, Error?) -> Void) {
        let heartRateType = HKQuantityType.quantityType(forIdentifier: .heartRate)!
        
        healthStore.requestAuthorization(toShare: [], read: [heartRateType]) { (success, error) in
            completion(success, error)
        }
    }
    
    func fetchHeartRateData(completion: @escaping (Double?, Error?) -> Void) {
        let heartRateType = HKQuantityType.quantityType(forIdentifier: .heartRate)!
        let now = Date()
        let tenMinutesAgo = Calendar.current.date(byAdding: .minute, value: -10, to: now)!
        let predicate = HKQuery.predicateForSamples(withStart: tenMinutesAgo, end: now, options: .strictStartDate)
        
        let query = HKSampleQuery(sampleType: heartRateType, predicate: predicate, limit: 1, sortDescriptors: nil) { (query, samples, error) in
            DispatchQueue.main.async {
                if let heartRateSample = samples?.first as? HKQuantitySample {
                    let heartRateValue = heartRateSample.quantity.doubleValue(for: HKUnit(from: "count/min"))
                    completion(heartRateValue, nil)
                } else if let error = error {
                    completion(nil, error)
                } else {
                    completion(nil, nil) // No heart rate data available in the last 10 minutes
                }
            }
        }
        healthStore.execute(query)
    }
}
