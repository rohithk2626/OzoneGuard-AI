# Machine Learning Pipeline

```
python -m ml.collect_data import-export data/raw/browser_export/ozoneguard_training_data.csv.gz
python -m ml.preprocess          # -> data/intermediate/cleaned.parquet
python -m ml.features            # -> data/processed/{train,val,test,spatial_holdout}.parquet
python -m ml.train_xgboost       # -> models/xgboost/   (XGBoost, default model)
python -m ml.train_lstm          # -> models/lstm/      (LSTM, needs requirements-lstm.txt)
python -m ml.compare_models      # -> docs/model-comparison.md
```

| File | Role |
|---|---|
| `features.py` | Direct multi-horizon feature rows used by XGBoost (training and live inference) |
| `train_xgboost.py` | Baselines, 5 model families, selection, conformal ranges, test evaluation, saves `models/xgboost/` |
| `lstm.py` | LSTM inputs (48 h history window, 24 h forecast window) and the NumPy forward pass used for serving |
| `train_lstm.py` | Trains the encoder-decoder LSTM with PyTorch, same split / metrics / conformal ranges, saves `models/lstm/` |
| `compare_models.py` | Side-by-side test results of both models |

Both models share `models/climatology.parquet` (train-period climatology used for anomalies).
