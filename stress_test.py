import time
import math
import multiprocessing
import os

def cpu_stressor(duration):
    end_time = time.time() + duration
    while time.time() < end_time:
        _ = math.factorial(500)

def memory_leak_stressor(duration):
    chunks = []
    for _ in range(duration // 2):
        chunks.append(bytearray(128 * 1024 * 1024))
        time.sleep(2)
    del chunks

def disk_io_stressor(duration):
    end_time = time.time() + duration
    temp_file = f"temp_anomaly_data_{os.getpid()}.tmp"
    while time.time() < end_time:
        with open(temp_file, "w") as f:
            f.write("A" * 1024 * 1024 * 50)
        os.remove(temp_file)

def log_attack(f, attack_name, start, end):
    f.write(f"{attack_name},{start},{end}\n")
    f.flush()

if __name__ == "__main__":
    print("=== ACADEMIC ANOMALY INJECTOR (30-MIN GOLD STANDARD) ===")
    input("Press ENTER to begin the 30-minute injection sequence...")

    with open("ground_truth_log.txt", "w") as log_file:
        log_file.write("Attack_Type,Start_Timestamp,End_Timestamp\n")

        for i in range(1, 6):
            print(f"\n======================================")
            print(f"       STARTING ROUND {i} OF 5")
            print(f"======================================")

            # TEST 1: CPU (30s)
            print(f"--- [Round {i}] TEST 1: CPU SPIKE ---")
            cores = max(1, multiprocessing.cpu_count() // 2)
            processes = [multiprocessing.Process(target=cpu_stressor, args=(30,)) for _ in range(cores)]
            
            start_t = time.time()
            for p in processes: p.start()
            for p in processes: p.join()
            end_t = time.time()
            
            log_attack(log_file, "CPU_Spike", start_t, end_t)
            print("[-] Cooling down for 3 minutes...")
            time.sleep(180)

            # TEST 2: Memory (20s)
            print(f"--- [Round {i}] TEST 2: MEMORY LEAK ---")
            mem_p = multiprocessing.Process(target=memory_leak_stressor, args=(20,))
            
            start_t = time.time()
            mem_p.start()
            mem_p.join()
            end_t = time.time()
            
            log_attack(log_file, "Memory_Leak", start_t, end_t)
            print("[-] Cooling down for 3 minutes...")
            time.sleep(180)

            # TEST 3: Disk I/O (30s)
            print(f"--- [Round {i}] TEST 3: DISK I/O ANOMALY ---")
            io_p = multiprocessing.Process(target=disk_io_stressor, args=(30,))
            
            start_t = time.time()
            io_p.start()
            io_p.join()
            end_t = time.time()
            
            log_attack(log_file, "Disk_IO", start_t, end_t)
            
            if i < 5:
                print("[-] Cooling down for 3 minutes before next round...")
                time.sleep(180)

    print("\n=== 30-MINUTE EVALUATION COMPLETE ===")
    print("You now have 'research_results.csv' AND 'ground_truth_log.txt'!")