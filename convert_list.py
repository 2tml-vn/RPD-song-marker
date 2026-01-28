import json
import re
import os
import subprocess

def convert():
    print("--- RPD LIST CONVERTER ---")
    print("Paste your list below (Format: MM:SS Title).")
    print("Type 'DONE' on a new line when finished.")
    print("-" * 30)
    
    input_lines = []
    while True:
        line = input()
        if line.strip().upper() == 'DONE':
            break
        input_lines.append(line)
    
    results = {}
    for line in input_lines:
        line = line.strip()
        # Regex to find timestamp at start: 0:33 or 10:33 or 1:05:30
        match = re.match(r'^(\d{1,2}:\d{2}(?:\d{2})?)\s+(.*)$', line)
        if match:
            ts, title = match.groups()
            results[ts] = title.strip()
            
    if not results:
        print("Error: No valid timestamps found.")
        return

    vid_id = input("\nEnter the YouTube ID for this video: ").strip()
    if not vid_id:
        print("Error: YouTube ID required.")
        return

    train_dir = "train_data"
    if not os.path.exists(train_dir):
        os.makedirs(train_dir)

    output_file = os.path.join(train_dir, f"progress_{vid_id}.json")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=4)
        
    print(f"\nSUCCESS: Created {output_file} with {len(results)} songs.")
    
    do_train = input("\nDo you want to feed this to the AI now? [y/n]: ").strip().lower()
    if do_train == 'y':
        print(f"Executing: python active_trainer_pro.py {vid_id} \"{output_file}\"")
        subprocess.run(f"python active_trainer_pro.py {vid_id} \"{output_file}\"", shell=True)

if __name__ == "__main__":
    convert()