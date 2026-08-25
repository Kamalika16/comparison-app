import pandas as pd


def load_records(path: str, sheet=0) -> list[dict]:
    """Read an Excel sheet into a list of plain dicts, column names untouched.
    No interpretation happens here — that's the LLM's job now."""
    df = pd.read_excel(path, sheet_name=sheet, dtype=object)
    df = df.dropna(how="all")                # drop fully empty rows
    df = df.dropna(axis=1, how="all")         # drop fully empty columns
    df = df.loc[:, ~df.columns.astype(str).str.startswith("Unnamed")]  # drop ghost columns
    print(f"DEBUG {path}: {len(df)} rows, columns: {list(df.columns)}")  # temporary, remove later
    for col in df.columns:
        df[col] = df[col].apply(
            lambda v: v.strftime("%Y-%m-%d") if hasattr(v, "strftime") else v
        )
    return df.to_dict(orient="records")