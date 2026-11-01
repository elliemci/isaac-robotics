#!/bin/bash
# Local synthetic data generation with the Isaac Sim installed on this machine.
# Based on NVIDIA-AI-IOT/synthetic_data_generation_training_workflow (MIT, see ../LICENSE-NVIDIA-AI-IOT.md).
# Changes: Isaac Sim path comes from $ISAAC_SIM_PATH (default ~/isaacsim) and the script
# can be started from any directory.
#
# Usage:  ISAAC_SIM_PATH=/path/to/isaacsim ./generate_data.sh
# Output: ../palletjack_sdg/palletjack_data/{distractors_warehouse,distractors_additional,no_distractors}

# This is the path where Isaac Sim is installed which contains the python.sh script
ISAAC_SIM_PATH="${ISAAC_SIM_PATH:-$HOME/isaacsim}"

## Go to location of the SDG script
cd "$(dirname "$(readlink -f "$0")")/../palletjack_sdg" || exit 1
SCRIPT_PATH="${PWD}/standalone_palletjack_sdg.py"
OUTPUT_WAREHOUSE="${PWD}/palletjack_data/distractors_warehouse"
OUTPUT_ADDITIONAL="${PWD}/palletjack_data/distractors_additional"
OUTPUT_NO_DISTRACTORS="${PWD}/palletjack_data/no_distractors"


## Go to Isaac Sim location for running with ./python.sh
cd "$ISAAC_SIM_PATH" || { echo "ISAAC_SIM_PATH not found: $ISAAC_SIM_PATH"; exit 1; }

echo "Starting Data Generation"

./python.sh $SCRIPT_PATH --height 544 --width 960 --num_frames 2000 --distractors warehouse --data_dir $OUTPUT_WAREHOUSE

./python.sh $SCRIPT_PATH --height 544 --width 960 --num_frames 2000 --distractors additional --data_dir $OUTPUT_ADDITIONAL

./python.sh $SCRIPT_PATH --height 544 --width 960 --num_frames 1000 --distractors None --data_dir $OUTPUT_NO_DISTRACTORS
