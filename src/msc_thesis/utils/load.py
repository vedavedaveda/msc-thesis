"""
AFC (Automated Fare Collection) data loader and trip-level preprocessor.

load_dataset()          -- decrypt and filter raw Rejsekort data for one date
filter_dataset()        -- keep only complete, in-area trips; map stops to clusters
load_trips()            -- load pre-processed recurrent_traveler_trips.csv directly
train_test_split_sim()  -- reproducible 75/25 split used across all notebooks
"""

import os
import re
import subprocess
from pathlib import Path
import pickle
import pandas as pd
import polars as pl
import numpy as np
from dotenv import load_dotenv

CACHE_ALL       = 'data/raptor_all_3246.pkl'
SEED            = 42

def normalize_stop_id(value):
    text = "" if value is None else str(value)
    text = text.replace("ODK:", "")
    text = re.sub(r"\D", "", text)
    text = text.lstrip("0")
    return text or None


def load_dataset(date, apply_filter=True, areas=None):
    load_dotenv()
    year = date[-4:]

    encrypted_file = os.environ["REJSEKORT_FILE"]
    if year != "2017":
        encrypted_file = encrypted_file.replace("2017", year)

    password = os.environ["REJSEKORT_PASS"]

    output_csv = f"data/trips/RejseData_{date}.csv"

    overrides = {
        "Kortnr_Kryp": pl.String,
        "StopPointId": pl.String,
        "RuteId": pl.String,
        "ContractorId": pl.String,
        "ProduktFamilie": pl.String,
    }

    if os.path.exists(output_csv):
        print(f"{output_csv} already exists. Loading directly.")
        df = pl.read_csv(output_csv, schema_overrides=overrides)

        if apply_filter and "Msgreportdate" in df.columns:
            print(f"Unfiltered dataset shape: {df.shape}")
            df = filter_dataset(df, areas)
            print(f"Filtered dataset shape: {df.shape}")
            df.write_csv(output_csv)

        return df

    cmd = (
        f"openssl enc -d -aes-256-cbc -salt -pbkdf2 -in {encrypted_file} -pass pass:{password} | "
        f"tar xzO | "
        f"iconv -f ISO-8859-1 -t UTF-8 | "
        f"(head -n 1 && grep {date})"
    )

    Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    with open(output_csv, "w") as f:
        process = subprocess.Popen(cmd, shell=True, stdout=f)
        process.wait()

    df = pl.read_csv(output_csv, schema_overrides=overrides)

    if apply_filter and "Msgreportdate" in df.columns:
        print(f"Unfiltered dataset shape: {df.shape}")
        df = filter_dataset(df, areas)
        print(f"Filtered dataset shape: {df.shape}")
        df.write_csv(output_csv)

    return df


def filter_dataset(df, areas=None):
    if areas is None:
        areas = ["Hovedstadsområdet"]

    stop_cluster_path = Path(__file__).resolve().parent.parent / "data" / "geospatial" / "stop_to_cluster_with_plot_status.csv"
    if not stop_cluster_path.exists():
        raise FileNotFoundError(
            f"Plotted stop-cluster CSV not found: {stop_cluster_path}. "
            "Generate it first with plot_stop_clusters_folium.py."
        )

    stop_cluster = pd.read_csv(
        stop_cluster_path,
        usecols=["stop_id_clean", "cluster_plotted"],
        low_memory=False,
    )
    stop_cluster["stop_id_clean"] = stop_cluster["stop_id_clean"].map(normalize_stop_id)
    stop_cluster["cluster_plotted"] = stop_cluster["cluster_plotted"].fillna(False).astype(bool)
    plotted_stop_ids = (
        stop_cluster.loc[stop_cluster["cluster_plotted"], "stop_id_clean"].dropna().astype(str).unique().tolist()
    )

    selection = [
        "FiCo",
        "FiSuCo",
        "FiSuSuCo",
        "FiCoTrCo",
        "FiCoTrCoTrCo",
        "FiSuSuSuCo",
        "FiSuCoTrCo",
        "FiCoTrSuCo",
        "FiSuCoTrSuCo",
        "FiSuSuSuSuCo",
        "FiSuSuCoTrCo",
        "FiCoTrCoTrCoTrCo",
        "FiSuSuSuSuSuCo",
        "FiCoTrSuSuCo",
        "FiSuCoTrCoTrCo",
        "FiSuSuCoTrSuCo",
        "FiCoTrCoTrSuCo",
        "FiSuCoTrSuSuCo",
        "FiCoTrSuCoTrCo",
        "FiSuSuCoTrSuSuCo",
        "FiSuSuSuCoTrCo",
        "FiSuSuCoTrCoTrCo",
        "FiSuSuSuSuCoTrCo",
        "FiCoTrCoTrCoTrCoTrCo",
    ]

    bus_contractors = [
        "City-Trafik (Movia TV)",
        "Arriva (Movia TV)",
        "Arriva (Movia TH)",
        "City-Trafik (Movia TH)",
        "De Hvide Busser (Movia)",
        "Dito Bus (Movia TV-nord)",
        "Nobina (Movia TH)",
        "De Blaa Omnibusser (Movia TH)",
        "Netbus",
        "Anchersens Rute (Movia TH)",
        "Ørslev Turisttrafik (Movia TS)",
        "Nobina (Movia TS)",
        "Lokalbussen",
        "Kruse (Movia TS)",
        "Arriva (Movia TS)",
        "Torbens Rute (Movia TV)",
        "Skørringe Turistbusser (Movia TS)",
        "Metro",
        "Helsingør Turisttrafik",
        "Dyssel's Busser",
        "Aarhus Sporveje",
        "Keolis (Fynbus)",
        "Arriva (NT)",
        "Tidebus (Fynbus)",
        "Brande Buslinier Aps",
        "Nettbus (NT)",
        "De Grønne Busser",
        "Arriva Danmark",
        "17-Thykjær A/S",
        "4-Rutebilselskabet Haderslev A/S",
        "21-Tide Bus",
        "Turistbus",
        "Odense By Busser",
        "Holstebro Turistbus",
        "18-Arriva",
        "Herning Bilen Specialruter (ST)",
        "150-Tidebus Danmark A/S",
        "City Trafik (NT)",
        "Bergholdt",
        "Nobina Danmark",
        "Arriva (Fynbus)",
        "58-De Blå Busser",
        "Lemvig Turist",
        "327-City Trafik A/S",
        "Silkebus",
        "Hjørring Citybus",
        "Solsiden",
        "322-Todbjerg City A/S - Midt",
        "7-Blåvandshuk Turisttrafik",
        "Nyborg Rejser",
        "De Blaa Busser",
    ]

    tog_contractors = [
        "DSB",
        "Lokalbanen A/S",
        "Regionstog A/S",
        "2015",
        "Trafikselskabet Movia",
        "NT",
        "DSB S-tog A/S",
    ]

    df = df.with_columns(
        pl.col("Msgreportdate").str.to_datetime(strict=False).alias("Msgreportdate_dt"),
        pl.col("RuteId").fill_null("").str.replace_all("-", ""),
        pl.col("StopPointNr").cast(pl.String).fill_null("nan"),
        pl.col("StopPointId").cast(pl.String).fill_null("nan"),
        pl.col("ContractorId").cast(pl.String).fill_null(""),
        pl.col("Msgreportdate").cast(pl.String).fill_null(""),
        pl.when(pl.col("ModalKomb") == "Bus")
        .then(pl.lit("Bus"))
        .when((pl.col("ModalKomb") == "Tog") & (pl.col("ContractorId") == "Metro"))
        .then(pl.lit("Metro"))
        .when(pl.col("ModalKomb") == "Tog")
        .then(pl.lit("Tog"))
        .when((pl.col("ModalKomb") == "Tog+Bus") & (pl.col("ContractorId") == "Metro"))
        .then(pl.lit("Metro"))
        .when(
            (pl.col("ModalKomb") == "Tog+Bus")
            & pl.col("ContractorId").is_in(bus_contractors)
        )
        .then(pl.lit("Bus"))
        .when(
            (pl.col("ModalKomb") == "Tog+Bus")
            & pl.col("ContractorId").is_in(tog_contractors)
        )
        .then(pl.lit("Tog"))
        .otherwise(pl.lit("999"))
        .alias("Mode"),
    ).filter(pl.col("Msgreportdate_dt").is_not_null())

    df_trips = df.group_by("turngl").agg(
        pl.col("Kortnr_Kryp").min(),
        pl.col("ContractorId").str.join(" ").alias("ContractorSequence"),
        pl.col("Msgreportdate").str.join(" ").alias("TimeSequence"),
        pl.col("StopPointNr").str.join(";").alias("StopNbSequence"),
        pl.col("StopPointId").str.join(";").alias("StopIdSequence"),
        pl.col("RuteId").str.join("-").alias("RuteIdSeq"),
        pl.col("Mode").str.join("-").alias("ModeSeq"),
        pl.col("Msgreportdate_dt").min().alias("Start_Time"),
        pl.col("Msgreportdate_dt").max().alias("End_Time"),
        pl.col("StopPointNr").first().alias("origin"),
        pl.col("StopPointNr").last().alias("destination"),
        pl.col("StopPointId").first().alias("origin_n"),
        pl.col("StopPointId").last().alias("destination_n"),
        pl.col("PassagerAntal1").max(),
        pl.col("PassagerAntal2").max(),
        pl.col("PassagerAntal3").max(),
        pl.col("NyUdførende").first(),
        pl.col("turtype").first(),
        pl.col("ModalKomb").first(),
        pl.col("TakstOmraade").first(),
        pl.col("ProduktFamilie").first(),
    )

    df_trips = (
        df_trips.with_columns(pl.col("RuteIdSeq").str.split("-").alias("RuteIdSeq2"))
        .with_columns(
            (
                (pl.col("End_Time") - pl.col("Start_Time")).dt.total_seconds() / 60.0
            ).alias("TT(min)"),
            (
                pl.col("PassagerAntal1")
                + pl.col("PassagerAntal2")
                + pl.col("PassagerAntal3")
            ).alias("TotalPass"),
            pl.when(
                (pl.col("PassagerAntal1") > 0)
                & (pl.col("PassagerAntal2") == 0)
                & (pl.col("PassagerAntal3") == 0)
            )
            .then(1)
            .when(
                (pl.col("PassagerAntal1") > 0)
                & (pl.col("PassagerAntal2") > 0)
                & (pl.col("PassagerAntal3") == 0)
            )
            .then(2)
            .otherwise(3)
            .alias("PassTypes"),
        )
        .drop(["PassagerAntal1", "PassagerAntal2", "PassagerAntal3"])
    )

    df_trips = df_trips.filter(
        pl.col("TakstOmraade").is_in(areas)
        & pl.col("turtype").is_in(selection)
        & (pl.col("origin") != pl.col("destination"))
        & (pl.col("TT(min)") > 0.5)
        & (pl.col("TT(min)") <= 180)
    )

    df_trips = df_trips.with_columns(
        pl.col("origin").cast(pl.String).map_elements(normalize_stop_id, return_dtype=pl.String).alias(
            "origin_stop_id_clean"
        ),
        pl.col("destination").cast(pl.String).map_elements(normalize_stop_id, return_dtype=pl.String).alias(
            "destination_stop_id_clean"
        ),
    )

    df_trips = df_trips.filter(
        pl.col("origin_stop_id_clean").is_in(plotted_stop_ids)
        & pl.col("destination_stop_id_clean").is_in(plotted_stop_ids)
    ).drop(["origin_stop_id_clean", "destination_stop_id_clean"])

    df_trips = df_trips.drop(["ProduktFamilie", "PassTypes", "RuteIdSeq2"])

    return df_trips


# ── Data loaders ─────────────────────────────────────────────────────────────
def load_trips(path='data/trips/recurrent_traveler_trips.csv'):
    trips = pd.read_csv(path, low_memory=False)
    trips['Start_Time'] = pd.to_datetime(trips['Start_Time'])
    trips['End_Time']   = pd.to_datetime(trips['End_Time'])
    return trips


def load_sim_df(path=CACHE_ALL):
    with open(path, 'rb') as f:
        all_results = pickle.load(f)
    return pd.DataFrame(all_results)


def train_test_split_sim(sim_df, seed=SEED, train_frac=0.75):
    """Reproducible 75/25 split used across all cells."""
    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(sim_df))
    n_train = int(train_frac * len(sim_df))
    tr = sim_df.iloc[idx[:n_train]].reset_index(drop=True)
    te = sim_df.iloc[idx[n_train:]].reset_index(drop=True)
    return tr, te