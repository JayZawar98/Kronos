import pickle
import random
import numpy as np
import pandas as pd
import torch
from torch.utils.data import Dataset

# =====================================================================
# Qlib Dataset (Originally from finetune/dataset.py)
# =====================================================================
class QlibDataset(Dataset):
    """A PyTorch Dataset for handling Qlib financial time series data."""
    def __init__(self, data_type: str = 'train', config=None):
        if config is None:
            from finetune.config import Config
            self.config = Config()
        else:
            self.config = config

        if data_type not in ['train', 'val']:
            raise ValueError("data_type must be 'train' or 'val'")
        self.data_type = data_type

        self.py_rng = random.Random(self.config.seed)

        if data_type == 'train':
            self.data_path = f"{self.config.dataset_path}/train_data.pkl"
            self.n_samples = self.config.n_train_iter
        else:
            self.data_path = f"{self.config.dataset_path}/val_data.pkl"
            self.n_samples = self.config.n_val_iter

        with open(self.data_path, 'rb') as f:
            self.data = pickle.load(f)

        self.window = self.config.lookback_window + self.config.predict_window + 1
        self.symbols = list(self.data.keys())
        self.feature_list = self.config.feature_list
        self.time_feature_list = self.config.time_feature_list

        self.indices = []
        for symbol in self.symbols:
            df = self.data[symbol].reset_index()
            series_len = len(df)
            num_samples = series_len - self.window + 1

            if num_samples > 0:
                df['minute'] = df['datetime'].dt.minute
                df['hour'] = df['datetime'].dt.hour
                df['weekday'] = df['datetime'].dt.weekday
                df['day'] = df['datetime'].dt.day
                df['month'] = df['datetime'].dt.month
                self.data[symbol] = df[self.feature_list + self.time_feature_list]

                for i in range(num_samples):
                    self.indices.append((symbol, i))

        self.n_samples = min(self.n_samples, len(self.indices))

    def set_epoch_seed(self, epoch: int):
        epoch_seed = self.config.seed + epoch
        self.py_rng.seed(epoch_seed)

    def __len__(self) -> int:
        return self.n_samples

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        random_idx = self.py_rng.randint(0, len(self.indices) - 1)
        symbol, start_idx = self.indices[random_idx]

        df = self.data[symbol]
        end_idx = start_idx + self.window
        win_df = df.iloc[start_idx:end_idx]

        x = win_df[self.feature_list].values.astype(np.float32)
        x_stamp = win_df[self.time_feature_list].values.astype(np.float32)

        past_len = self.config.lookback_window
        past_x = x[:past_len]
        x_mean = np.mean(past_x, axis=0)
        x_std  = np.std(past_x, axis=0)

        x = (x - x_mean) / (x_std + 1e-5)
        x = np.clip(x, -self.config.clip, self.config.clip)

        return torch.from_numpy(x), torch.from_numpy(x_stamp)


# =====================================================================
# CSV Dataset (Originally from finetune_csv/finetune_base_model.py)
# =====================================================================
class CustomKlineDataset(Dataset):
    def __init__(self, data_path, data_type='train', lookback_window=90, predict_window=10, 
                 clip=5.0, seed=100, train_ratio=0.7, val_ratio=0.15, test_ratio=0.15):
        self.data_path = data_path
        self.data_type = data_type
        self.lookback_window = lookback_window
        self.predict_window = predict_window
        self.window = lookback_window + predict_window + 1
        self.clip = clip
        self.seed = seed
        self.train_ratio = train_ratio
        self.val_ratio = val_ratio
        self.test_ratio = test_ratio
        
        self.feature_list = ['open', 'high', 'low', 'close', 'volume', 'amount']
        self.time_feature_list = ['minute', 'hour', 'weekday', 'day', 'month']
        
        self.py_rng = random.Random(seed)
        
        self._load_and_preprocess_data()
        self._split_data_by_time()
        
        self.n_samples = len(self.data) - self.window + 1
            
    def _load_and_preprocess_data(self):
        df = pd.read_csv(self.data_path)
        df['timestamps'] = pd.to_datetime(df['timestamps'])
        df = df.sort_values('timestamps').reset_index(drop=True)
        
        self.timestamps = df['timestamps'].copy()
        df['minute'] = df['timestamps'].dt.minute
        df['hour'] = df['timestamps'].dt.hour
        df['weekday'] = df['timestamps'].dt.weekday
        df['day'] = df['timestamps'].dt.day
        df['month'] = df['timestamps'].dt.month
        
        self.data = df[self.feature_list + self.time_feature_list].copy()
        
        if self.data.isnull().any().any():
            self.data = self.data.fillna(method='ffill')
    
    def _split_data_by_time(self):
        total_length = len(self.data)
        train_end = int(total_length * self.train_ratio)
        val_end = int(total_length * (self.train_ratio + self.val_ratio))
        
        if self.data_type == 'train':
            self.data = self.data.iloc[:train_end].copy()
            self.timestamps = self.timestamps.iloc[:train_end].copy()
        elif self.data_type == 'val':
            self.data = self.data.iloc[train_end:val_end].copy()
            self.timestamps = self.timestamps.iloc[train_end:val_end].copy()
        elif self.data_type == 'test':
            self.data = self.data.iloc[val_end:].copy()
            self.timestamps = self.timestamps.iloc[val_end:].copy()
    
    def set_epoch_seed(self, epoch):
        epoch_seed = self.seed + epoch
        self.py_rng.seed(epoch_seed)
        self.current_epoch = epoch
    
    def __len__(self):
        return self.n_samples
    
    def __getitem__(self, idx):
        max_start = len(self.data) - self.window
        if max_start <= 0:
            raise ValueError("Data length insufficient to create samples")
        
        if self.data_type == 'train':
            epoch = getattr(self, 'current_epoch', 0)
            start_idx = (idx * 9973 + (epoch + 1) * 104729) % (max_start + 1)
        else:
            start_idx = idx % (max_start + 1)
        
        end_idx = start_idx + self.window
        window_data = self.data.iloc[start_idx:end_idx]
        
        x = window_data[self.feature_list].values.astype(np.float32)
        x_stamp = window_data[self.time_feature_list].values.astype(np.float32)
        
        x_mean, x_std = np.mean(x, axis=0), np.std(x, axis=0)
        x = (x - x_mean) / (x_std + 1e-5)
        x = np.clip(x, -self.clip, self.clip)
        
        return torch.from_numpy(x), torch.from_numpy(x_stamp)
