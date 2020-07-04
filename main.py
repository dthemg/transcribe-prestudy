import os
from scipy.io import wavfile
import numpy as np

import pearls


def save_file(data, filename):
    
    os.makedirs("results", exist_ok=True)
    save_path = os.path.join("results", filename)
    print(f"Saving {save_path}...")
    np.save(save_path, data)



if __name__ == "__main__":
    """Load data"""
    DATA_PATH = os.path.join("data", "bach_air.wav")
    sample_rate, data = wavfile.read(DATA_PATH, mmap=False)

    """Test code"""
    N = 10000
    S = 10000
    signal = data[S : S + N, 0]
    forgetting_factor = 0.995
    smoothness_factor = 1e4
    max_num_harmonics = 3
    sampling_frequency = sample_rate
    minimum_pitch = 50
    maximum_pitch = 500
    initial_frequency_resolution = 50

    rls_filter_hist, pitch_hist = pearls.PEARLS(
        signal,
        forgetting_factor,
        smoothness_factor,
        max_num_harmonics,
        sampling_frequency,
        minimum_pitch,
        maximum_pitch,
        initial_frequency_resolution,
    )

    save_file(rls_filter_hist, "rls_history")
    save_file(pitch_hist, "pitch_est_history")
