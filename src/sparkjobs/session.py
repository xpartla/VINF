"""SparkSession for the jobs: local defaults under plain `python`, untouched settings under spark-submit."""
import json
import os
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", message="PySpark does not yet fully support pandas")

SRC_DIR = Path(__file__).resolve().parents[1]
LOCAL_DEFAULTS = {
    "spark.master": "local[*]",
    "spark.driver.memory": "8g",
    "spark.sql.shuffle.partitions": "64",
    "spark.ui.showConsoleProgress": "false",
}


def under_spark_submit():
    return "PYSPARK_GATEWAY_PORT" in os.environ


def get_spark(app_name):
    from pyspark.sql import SparkSession

    builder = SparkSession.builder.appName(app_name)
    if not under_spark_submit():
        # python workers import extractor/wiki/... from src/ (spark-submit ships them with --py-files)
        os.environ["PYTHONPATH"] = os.pathsep.join(p for p in (str(SRC_DIR), os.environ.get("PYTHONPATH")) if p)
        for key, value in LOCAL_DEFAULTS.items():
            builder = builder.config(key, os.environ.get("VINF_" + key.replace(".", "_").upper(), value))
    spark = builder.getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    try:   # glob input paths make FileStreamSink log a harmless FileNotFoundException
        jvm = spark.sparkContext._jvm
        jvm.org.apache.logging.log4j.core.config.Configurator.setLevel(
            "org.apache.spark.sql.execution.streaming", jvm.org.apache.logging.log4j.Level.ERROR)
    except Exception:
        pass
    return spark


def uri(base, *parts):
    """hdfs://, file: ... joined with "/"; plain local paths made absolute (the default FS may be HDFS)."""
    base = str(base)
    if "://" in base or base.startswith("file:"):
        return "/".join([base.rstrip("/")] + list(parts))
    return str(Path(base).resolve().joinpath(*parts))


def write_json(path, obj, spark=None):
    """Small result file from the driver; on hdfs:// etc. a one-part text dir written by Spark."""
    text = json.dumps(obj, indent=2, ensure_ascii=False)
    path = str(path)
    if "://" in path and not path.startswith("file:"):
        spark.createDataFrame([(text,)], "value string").coalesce(1).write.mode("overwrite").text(path)
        return
    p = Path(path.replace("file://", "").replace("file:", ""))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text + "\n", encoding="utf-8")
