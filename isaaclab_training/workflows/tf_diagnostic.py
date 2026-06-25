import sys
import struct
from tensorboard.backend.event_processing import event_accumulator

if len(sys.argv) < 2:
    print("Error: Please provide the path to the tfevents file.")
    sys.exit(1)

event_file = sys.argv[1]

# Diagnostic script to find out whatis in inside the event file
# load everything including Tensors size_guidance=0 means load all events
ea = event_accumulator.EventAccumulator(event_file, size_guidance={event_accumulator.TENSORS: 0})
ea.Reload()

print("\n=========================================")
print(f"Analyzing Event File: {event_file}")
print("=========================================\n")

# Print all Scalar Tag Names
scalars = ea.Tags().get('scalars', [])
print(f"Found {len(scalars)} Scalar Tags:")
for tag in scalars:
    print(f"  - [Scalar] {tag}")

# Print all Tensor Tag Names
tensors = ea.Tags().get('tensors', [])
print(f"\nFound {len(tensors)} Tensor Tags:")
for tag in tensors:
    print(f"  - [Tensor] {tag}")

# Print all Histogram Tag Names
histograms = ea.Tags().get('histograms', [])
print(f"\nFound {len(histograms)} Histogram Tags:")
for tag in histograms:
    print(f"  - [Histogram] {tag}")

print("\n=========================================")

# define the targets and print out training statistis from the tf event file for the exact names discovered above, see read_events.py
