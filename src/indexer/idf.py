"""TF and IDF variants; the probabilistic IDF is excluded by the course rules."""
import math


def tf_raw(tf):
    return float(tf)


def tf_log(tf):
    return 1.0 + math.log(tf) if tf > 0 else 0.0


def tf_binary(tf):
    return 1.0 if tf > 0 else 0.0


def idf_classic(N, df, max_df=None):
    return math.log(N / df) if df else 0.0


def idf_smooth(N, df, max_df=None):
    return math.log((1 + N) / (1 + df)) + 1.0


def idf_max(N, df, max_df):
    return math.log(max_df / df) if df else 0.0


def idf_none(N, df, max_df=None):
    return 1.0


TF_METHODS = {"raw": tf_raw, "log": tf_log, "binary": tf_binary}
IDF_METHODS = {"classic": idf_classic, "smooth": idf_smooth, "max": idf_max, "none": idf_none}
DEFAULT_TF = "log"
DEFAULT_IDF = "classic"


def weight_key(tf_name, idf_name):
    return f"{tf_name}:{idf_name}"
