import sys
from tensorboard.backend.event_processing import event_accumulator

if len(sys.argv) < 2:
    print("Error: Please provide the path to the tfevents file.")
    sys.exit(1)

event_file = sys.argv[1]

# Load file metadata (size_guidance=0 ensures all scalar items are loaded)
ea = event_accumulator.EventAccumulator(event_file, size_guidance={event_accumulator.SCALARS: 0})
ea.Reload()

# print all tags
print(sorted(ea.Tags()["scalars"]))

# Define the exact names discovered in your log file
target_tags = [
    "Episode_Reward/end_effector_position_tracking",
    "Episode_Reward/end_effector_position_tracking_fine_grained",
    "Episode_Reward/end_effector_orientation_tracking",
    "Episode_Reward/action_rate",
    "Episode_Reward/joint_vel",
    "Episode_Reward/debug_distance" # added for debugging purpases
]

print("\n======================================================================")
print("                    REWARD METRICS SUMMARY REPORT                     ")
print("======================================================================")
# Print a clean tabular header
print(f"{'Metric Tag / Reward Component':<60} | {'Final Value':<12} | {'Average Value':<12}")
print("-" * 90)

for tag in target_tags:
    if tag in ea.Tags().get('scalars', []):
        events = ea.Scalars(tag)
        
        if events:
            # Extract all numerical values for this tag
            values = [event.value for event in events]
            
            # Calculate final and average statistics
            final_val = values[-1]
            avg_val = sum(values) / len(values)
            
            # Shorten the display name by removing the 'Episode_Reward/' prefix for cleaner reading
            display_name = tag.replace("Episode_Reward/", "")
            
            print(f"{display_name:<60} | {final_val:<12.4f} | {avg_val:<12.4f}")
        else:
            print(f"{tag:<60} | {'No Data':<12} | {'No Data':<12}")
    else:
        display_name = tag.replace("Episode_Reward/", "")
        print(f"[Missing] {display_name:<50} | {'N/A':<12} | {'N/A':<12}")

print("======================================================================\n")
