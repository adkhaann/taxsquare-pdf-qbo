import streamlit as st
import pandas as pd
import fitz
import re
import hashlib
from datetime import datetime


# =========================================================
# PAGE SETTINGS
# =========================================================

st.set_page_config(
    page_title="Tax Square PDF to QuickBooks Converter",
    page_icon="📄",
    layout="wide"
)

st.title("PDF to QuickBooks Converter")

st.write(
    "Convert supported Canadian bank and credit-card PDF statements into "
    "QuickBooks Online CSV or QuickBooks Desktop QBO files."
)

st.divider()


# =========================================================
# GENERAL HELPERS
# =========================================================

def clean_amount(value):

    if value is None:
        return 0.0

    value = (
        str(value)
        .replace(",", "")
        .replace("$", "")
        .replace("(", "-")
        .replace(")", "")
        .strip()
    )

    try:
        return float(value)
    except:
        return 0.0


def clean_qbo_text(text):

    text = str(text)

    text = text.replace("&", "and")
    text = text.replace("<", "")
    text = text.replace(">", "")
    text = text.replace("\n", " ")
    text = text.replace("\r", " ")

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def qbo_datetime(date_object):

    return (
        date_object.strftime("%Y%m%d")
        + "120000"
    )


def create_fitid(
    prefix,
    date_text,
    description,
    amount,
    occurrence
):

    source = (
        f"{prefix}|"
        f"{date_text}|"
        f"{description}|"
        f"{amount:.2f}|"
        f"{occurrence}"
    )

    digest = hashlib.sha256(
        source.encode("utf-8")
    ).hexdigest()

    return digest[:24]


# =========================================================
# TD CHEQUING HELPERS
# =========================================================

def get_chequing_statement_year(text):

    match = re.search(
        r"([A-Z]{3})\s*(\d{1,2})/(\d{2})\s*-\s*"
        r"([A-Z]{3})\s*(\d{1,2})/(\d{2})",
        text,
        re.IGNORECASE
    )

    if match:
        return 2000 + int(match.group(6))

    return datetime.now().year


def parse_chequing_date(
    date_text,
    statement_year
):

    try:

        parsed = datetime.strptime(
            f"{date_text}{statement_year}",
            "%b%d%Y"
        )

        return parsed.strftime(
            "%Y-%m-%d"
        )

    except:
        return date_text


def get_chequing_control_totals(text):

    credit_match = re.search(
        r"Credits\s+(\d+)\s+([\d,]+\.\d{2})",
        text,
        re.IGNORECASE
    )

    debit_match = re.search(
        r"Debits\s+(\d+)\s+([\d,]+\.\d{2})",
        text,
        re.IGNORECASE
    )

    result = {
        "credit_count": None,
        "credit_total": None,
        "debit_count": None,
        "debit_total": None
    }

    if credit_match:

        result["credit_count"] = int(
            credit_match.group(1)
        )

        result["credit_total"] = clean_amount(
            credit_match.group(2)
        )

    if debit_match:

        result["debit_count"] = int(
            debit_match.group(1)
        )

        result["debit_total"] = clean_amount(
            debit_match.group(2)
        )

    return result


def get_chequing_ending_balance(text):

    matches = re.findall(
        r"([\d,]+\.\d{2})\s*(OD)?",
        text,
        re.IGNORECASE
    )

    if not matches:
        return 0.0

    # Ending balance is not required for transaction import.
    # Use zero if we cannot identify it reliably.
    return 0.0


def get_chequing_account_id(text):

    match = re.search(
        r"\b\d{4}\s+\d{4}-(\d{7})\b",
        text
    )

    if match:
        return match.group(1)

    return "0000000"


# =========================================================
# TD CHEQUING PARSER
# =========================================================

def extract_td_chequing_transactions(
    pdf_bytes
):

    doc = fitz.open(
        stream=pdf_bytes,
        filetype="pdf"
    )

    full_text = ""

    for page in doc:
        full_text += page.get_text("text") + "\n"

    statement_year = (
        get_chequing_statement_year(
            full_text
        )
    )

    controls = (
        get_chequing_control_totals(
            full_text
        )
    )

    account_id = (
        get_chequing_account_id(
            full_text
        )
    )

    transactions = []

    # -----------------------------------------------------
    # IMPORTANT:
    #
    # This method reads each dated TD row and then identifies
    # the two transaction amount columns.
    # -----------------------------------------------------

    for page in doc:

        words = page.get_text("words")

        rows = {}

        for word in words:

            x0, y0, x1, y1, text = word[:5]

            row_key = round(
                y0 / 3
            ) * 3

            rows.setdefault(
                row_key,
                []
            )

            rows[row_key].append({
                "x0": x0,
                "x1": x1,
                "text": text
            })

        for row_y in sorted(
            rows.keys()
        ):

            row = sorted(
                rows[row_y],
                key=lambda item: item["x0"]
            )

            row_text = " ".join(
                item["text"]
                for item in row
            )

            date_match = re.search(
                r"\b"
                r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|"
                r"SEP|OCT|NOV|DEC)"
                r"(\d{2})"
                r"\b",
                row_text,
                re.IGNORECASE
            )

            if not date_match:
                continue

            date_token = (
                date_match.group(1).upper()
                +
                date_match.group(2)
            )

            if (
                "BALANCE FORWARD"
                in row_text.upper()
            ):
                continue

            amount_words = []

            for item in row:

                cleaned = (
                    item["text"]
                    .replace("$", "")
                    .replace(",", "")
                    .strip()
                )

                if re.fullmatch(
                    r"\d+\.\d{2}",
                    cleaned
                ):

                    amount_words.append({
                        "x": (
                            item["x0"]
                            +
                            item["x1"]
                        ) / 2,
                        "amount": clean_amount(
                            cleaned
                        )
                    })

            if not amount_words:
                continue

            # -------------------------------------------------
            # The far-right amount is the running balance.
            # Remove it when three amount values are present.
            # -------------------------------------------------

            amount_words = sorted(
                amount_words,
                key=lambda item: item["x"]
            )

            transaction_amounts = (
                amount_words[:-1]
                if len(amount_words) >= 2
                else amount_words
            )

            # -------------------------------------------------
            # Description ends before first transaction amount.
            # -------------------------------------------------

            first_amount_x = min(
                item["x"]
                for item in transaction_amounts
            )

            description_parts = []

            for item in row:

                center_x = (
                    item["x0"]
                    +
                    item["x1"]
                ) / 2

                if center_x < first_amount_x:

                    text = item["text"]

                    if (
                        text.upper()
                        != date_token
                    ):

                        description_parts.append(
                            text
                        )

            description = " ".join(
                description_parts
            ).strip()

            if not description:
                continue

            # -------------------------------------------------
            # TD statement transaction amount columns:
            #
            # left transaction amount = debit
            # right transaction amount = credit
            #
            # When only one transaction amount exists,
            # determine its side from its x position.
            # -------------------------------------------------

            debit = 0.0
            credit = 0.0

            page_width = (
                page.rect.width
            )

            for item in transaction_amounts:

                ratio = (
                    item["x"]
                    /
                    page_width
                )

                if ratio < 0.59:
                    debit = item["amount"]

                else:
                    credit = item["amount"]

            if (
                debit == 0
                and
                credit == 0
            ):
                continue

            transaction_date = (
                parse_chequing_date(
                    date_token,
                    statement_year
                )
            )

            transactions.append({
                "Date": transaction_date,
                "Description": description,
                "Debit": debit,
                "Credit": credit
            })

    doc.close()

    df = pd.DataFrame(
        transactions
    )

    if not df.empty:

        df["Debit"] = pd.to_numeric(
            df["Debit"],
            errors="coerce"
        ).fillna(0)

        df["Credit"] = pd.to_numeric(
            df["Credit"],
            errors="coerce"
        ).fillna(0)

        df = (
            df
            .drop_duplicates()
            .reset_index(drop=True)
        )

    statement_info = {
        "statement_type": "chequing",
        "control": controls,
        "account_id": account_id,
        "ending_balance": 0.0
    }

    return df, statement_info


# =========================================================
# CREDIT CARD SUMMARY
# =========================================================

def get_credit_card_summary(
    full_text
):

    summary = {
        "previous_balance": None,
        "payments_credits": None,
        "purchases_charges": None,
        "interest": None,
        "fees": None,
        "new_balance": None
    }

    patterns = {

        "previous_balance": [
            r"Previous\s+Balance[\s:$]*"
            r"\$?\s*([\d,]+\.\d{2})"
        ],

        "payments_credits": [
            r"Payments\s*&\s*Credits[\s:$-]*"
            r"\$?\s*([\d,]+\.\d{2})",

            r"Payments\s+and\s+Credits[\s:$-]*"
            r"\$?\s*([\d,]+\.\d{2})"
        ],

        "purchases_charges": [
            r"Purchases\s*&\s*Other\s+Charges"
            r"[\s:$]*\$?\s*([\d,]+\.\d{2})",

            r"Purchases\s+and\s+Other\s+Charges"
            r"[\s:$]*\$?\s*([\d,]+\.\d{2})"
        ],

        "interest": [
            r"Interest[\s:$]*"
            r"\$?\s*([\d,]+\.\d{2})"
        ],

        "fees": [
            r"Fees[\s:$]*"
            r"\$?\s*([\d,]+\.\d{2})"
        ],

        "new_balance": [
            r"NEW\s+BALANCE[\s:$]*"
            r"\$?\s*([\d,]+\.\d{2})"
        ]
    }

    for key, pattern_list in patterns.items():

        for pattern in pattern_list:

            match = re.search(
                pattern,
                full_text,
                re.IGNORECASE
            )

            if match:

                summary[key] = (
                    clean_amount(
                        match.group(1)
                    )
                )

                break

    # -----------------------------------------------------
    # If TD splits Purchases & Other Charges across PDF
    # blocks, calculate it from the statement equation.
    # -----------------------------------------------------

    if (
        summary["purchases_charges"]
        is None
        and
        summary["previous_balance"]
        is not None
        and
        summary["payments_credits"]
        is not None
        and
        summary["new_balance"]
        is not None
    ):

        interest = (
            summary["interest"]
            or 0.0
        )

        fees = (
            summary["fees"]
            or 0.0
        )

        summary["purchases_charges"] = round(

            summary["new_balance"]

            -

            summary["previous_balance"]

            +

            summary["payments_credits"]

            -

            interest

            -

            fees,

            2
        )

    return summary


# =========================================================
# CREDIT CARD HELPERS
# =========================================================

def get_credit_card_year(text):

    match = re.search(
        r"STATEMENT DATE:\s*"
        r"(?:January|February|March|April|May|June|July|"
        r"August|September|October|November|December)"
        r"\s+\d{1,2},\s*(20\d{2})",
        text,
        re.IGNORECASE
    )

    if match:
        return int(match.group(1))

    match = re.search(
        r"\b(20\d{2})\b",
        text
    )

    if match:
        return int(match.group(1))

    return datetime.now().year


def get_credit_card_account_id(
    text
):

    # Prefer explicit masked account-number line.

    patterns = [

        r"Account\s+Number:\s*"
        r"(?:\d{4}\s+)?"
        r"(?:\d{2}XX\s+XXXX\s+)?"
        r"(\d{4})",

        r"Account\s+Number.*?"
        r"(\d{4})\b",

        r"ending\s+in\s+"
        r"(\d{4})"
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:
            return match.group(1)

    return "0000"


# =========================================================
# TD CREDIT CARD TRANSACTION PARSER
#
# DO NOT CHANGE:
# THIS IS THE VERSION THAT PRODUCED:
#
# 39 transactions
# $1,523.70 charges
# $3,029.28 payments/credits
# =========================================================

def extract_td_credit_card_transactions(
    pdf_bytes
):

    doc = fitz.open(
        stream=pdf_bytes,
        filetype="pdf"
    )

    full_text = ""

    for page in doc:
        full_text += page.get_text("text") + "\n"

    statement_year = (
        get_credit_card_year(
            full_text
        )
    )

    summary = (
        get_credit_card_summary(
            full_text
        )
    )

    account_id = (
        get_credit_card_account_id(
            full_text
        )
    )

    transactions = []

    valid_months = {
        "JAN", "FEB", "MAR", "APR",
        "MAY", "JUN", "JUL", "AUG",
        "SEP", "OCT", "NOV", "DEC"
    }

    for page in doc:

        words = page.get_text("words")

        if not words:
            continue

        for date_word in words:

            x0, y0, x1, y1, month_text = (
                date_word[:5]
            )

            month_text = (
                month_text
                .strip()
                .upper()
            )

            if month_text not in valid_months:
                continue

            if not (
                40 <= x0 <= 60
            ):
                continue

            date_center_y = (
                y0 + y1
            ) / 2

            row_words = []

            for word in words:

                wx0, wy0, wx1, wy1, text = (
                    word[:5]
                )

                word_center_y = (
                    wy0 + wy1
                ) / 2

                if abs(
                    word_center_y
                    -
                    date_center_y
                ) <= 3.5:

                    if wx0 < 360:

                        row_words.append(
                            word
                        )

            row_words.sort(
                key=lambda item: item[0]
            )

            day = None

            for word in row_words:

                wx0, wy0, wx1, wy1, text = (
                    word[:5]
                )

                if (
                    55 <= wx0 <= 80
                    and
                    re.fullmatch(
                        r"\d{1,2}",
                        text.strip()
                    )
                ):

                    day = int(
                        text.strip()
                    )

                    break

            if day is None:
                continue

            amount_text = None

            for word in row_words:

                wx0, wy0, wx1, wy1, text = (
                    word[:5]
                )

                cleaned = text.strip()

                if (
                    295 <= wx0 <= 355
                    and
                    re.fullmatch(
                        r"-?\$[\d,]+\.\d{2}",
                        cleaned
                    )
                ):

                    amount_text = cleaned

                    break

            if amount_text is None:
                continue

            description_parts = []

            for word in row_words:

                wx0, wy0, wx1, wy1, text = (
                    word[:5]
                )

                if (
                    130 <= wx0 < 295
                ):

                    description_parts.append(
                        text.strip()
                    )

            description = " ".join(
                description_parts
            ).strip()

            if not description:
                continue

            numeric_amount = (
                clean_amount(
                    amount_text
                )
            )

            debit = 0.0
            credit = 0.0

            if numeric_amount < 0:

                credit = abs(
                    numeric_amount
                )

            else:

                debit = numeric_amount

            try:

                transaction_date = (
                    datetime.strptime(
                        f"{month_text} "
                        f"{day} "
                        f"{statement_year}",
                        "%b %d %Y"
                    )
                    .strftime(
                        "%Y-%m-%d"
                    )
                )

            except:

                transaction_date = (
                    f"{month_text} {day}"
                )

            transactions.append({
                "Date": transaction_date,
                "Description": description,
                "Debit": debit,
                "Credit": credit
            })

    doc.close()

    df = pd.DataFrame(
        transactions
    )

    if not df.empty:

        df["Debit"] = pd.to_numeric(
            df["Debit"],
            errors="coerce"
        ).fillna(0)

        df["Credit"] = pd.to_numeric(
            df["Credit"],
            errors="coerce"
        ).fillna(0)

        df = (
            df
            .drop_duplicates()
            .reset_index(drop=True)
        )

    statement_info = {
        "statement_type": "credit_card",
        "summary": summary,
        "account_id": account_id
    }

    return df, statement_info


# =========================================================
# QUICKBOOKS ONLINE CSV
# =========================================================

def generate_quickbooks_csv(
    df
):

    export_df = df.copy()

    export_df["Amount"] = (
        export_df["Credit"]
        -
        export_df["Debit"]
    )

    export_df = export_df[
        [
            "Date",
            "Description",
            "Amount"
        ]
    ]

    export_df["Date"] = (
        pd.to_datetime(
            export_df["Date"]
        )
        .dt.strftime(
            "%d/%m/%Y"
        )
    )

    return export_df.to_csv(
        index=False
    )


# =========================================================
# CHEQUING QBO
#
# KEEPING BANK QBO SEPARATE FROM CREDIT CARD.
# =========================================================

def generate_td_chequing_qbo(
    df,
    account_id
):

    working_df = df.copy()

    working_df["DateObject"] = (
        pd.to_datetime(
            working_df["Date"]
        )
    )

    first_date = (
        working_df["DateObject"]
        .min()
    )

    last_date = (
        working_df["DateObject"]
        .max()
    )

    start_date = (
        qbo_datetime(
            first_date
        )
    )

    end_date = (
        qbo_datetime(
            last_date
        )
    )

    server_time = (
        datetime.now()
        .strftime(
            "%Y%m%d%H%M%S"
        )
    )

    blocks = []

    duplicate_counter = {}

    for _, row in working_df.iterrows():

        debit = float(
            row["Debit"]
        )

        credit = float(
            row["Credit"]
        )

        amount = (
            credit - debit
        )

        date_object = (
            row["DateObject"]
        )

        date_text = (
            date_object.strftime(
                "%Y%m%d"
            )
        )

        description = clean_qbo_text(
            row["Description"]
        )

        key = (
            date_text,
            description,
            f"{amount:.2f}"
        )

        duplicate_counter[key] = (
            duplicate_counter.get(
                key,
                0
            )
            + 1
        )

        fitid = create_fitid(
            "TDCHEQ",
            date_text,
            description,
            amount,
            duplicate_counter[key]
        )

        trntype = (
            "DEBIT"
            if amount < 0
            else "CREDIT"
        )

        blocks.append(
            "<STMTTRN>\n"
            f"<TRNTYPE>{trntype}\n"
            f"<DTPOSTED>{qbo_datetime(date_object)}\n"
            f"<TRNAMT>{amount:.2f}\n"
            f"<FITID>{fitid}\n"
            f"<NAME>{description[:32]}\n"
            f"<MEMO>{description[:255]}\n"
            "</STMTTRN>"
        )

    transaction_text = "\n".join(
        blocks
    )

    return f"""OFXHEADER:100
DATA:OFXSGML
VERSION:102
SECURITY:NONE
ENCODING:USASCII
CHARSET:1252
COMPRESSION:NONE
OLDFILEUID:NONE
NEWFILEUID:NONE

<OFX>
<SIGNONMSGSRSV1>
<SONRS>
<STATUS>
<CODE>0
<SEVERITY>INFO
</STATUS>
<DTSERVER>{server_time}
<LANGUAGE>ENG
<FI>
<ORG>TD Canada Trust
<FID>004
</FI>
</SONRS>
</SIGNONMSGSRSV1>
<BANKMSGSRSV1>
<STMTTRNRS>
<TRNUID>1
<STATUS>
<CODE>0
<SEVERITY>INFO
</STATUS>
<STMTRS>
<CURDEF>CAD
<BANKACCTFROM>
<BANKID>004
<BRANCHID>00000
<ACCTID>{account_id}
<ACCTTYPE>CHECKING
</BANKACCTFROM>
<BANKTRANLIST>
<DTSTART>{start_date}
<DTEND>{end_date}
{transaction_text}
</BANKTRANLIST>
<LEDGERBAL>
<BALAMT>0.00
<DTASOF>{end_date}
</LEDGERBAL>
</STMTRS>
</STMTTRNRS>
</BANKMSGSRSV1>
</OFX>
"""


# =========================================================
# CREDIT CARD QBO
#
# IMPORTANT FIX:
#
# This version uses a conservative OFX 1.02 Web Connect
# credit-card structure.
#
# It intentionally avoids bank-only fields such as:
# BANKID
# BRANCHID
# ACCTTYPE
#
# Credit card uses CCACCTFROM only.
# =========================================================

def generate_td_credit_card_qbo(
    df,
    account_id,
    new_balance
):
    """
    Generate a QuickBooks Desktop Web Connect (.QBO) file
    for a TD Canada Trust credit-card statement.

    Key points:
    - Credit-card OFX wrapper: CREDITCARDMSGSRSV1 / CCSTMTRS
    - Charges are negative; payments/credits are positive
    - Uses TD Canada Trust's Intuit branding ID in addition to FI/FID
    - Adds OFX date timezone suffixes expected by QuickBooks Web Connect
    """

    working_df = df.copy()
    working_df["DateObject"] = pd.to_datetime(working_df["Date"])

    first_date = working_df["DateObject"].min()
    last_date = working_df["DateObject"].max()

    def ofx_dt(value):
        return value.strftime("%Y%m%d") + "120000[0:GMT]"

    start_date = ofx_dt(first_date)
    end_date = ofx_dt(last_date)
    server_time = datetime.now().strftime("%Y%m%d%H%M%S") + "[0:GMT]"

    transaction_blocks = []
    duplicate_counter = {}

    for _, row in working_df.iterrows():
        debit = float(row["Debit"])
        credit = float(row["Credit"])

        # Credit-card OFX convention:
        # purchase/charge = negative
        # payment/refund = positive
        amount = credit - debit

        date_object = row["DateObject"]
        date_text = date_object.strftime("%Y%m%d")
        description = clean_qbo_text(row["Description"])

        duplicate_key = (
            date_text,
            description,
            f"{amount:.2f}"
        )

        duplicate_counter[duplicate_key] = (
            duplicate_counter.get(duplicate_key, 0) + 1
        )

        fitid = create_fitid(
            "TDCC",
            date_text,
            description,
            amount,
            duplicate_counter[duplicate_key]
        )

        trntype = "DEBIT" if amount < 0 else "CREDIT"

        transaction_blocks.append(
            "<STMTTRN>\n"
            f"<TRNTYPE>{trntype}\n"
            f"<DTPOSTED>{ofx_dt(date_object)}\n"
            f"<TRNAMT>{amount:.2f}\n"
            f"<FITID>{fitid}\n"
            f"<NAME>{description[:32]}\n"
            f"<MEMO>{description[:255]}\n"
            "</STMTTRN>"
        )

    transactions_text = "\n".join(transaction_blocks)

    # Credit-card liability balance is negative in OFX.
    ledger_balance = (
        0.00
        if new_balance is None
        else -abs(float(new_balance))
    )

    # TD Canada Trust Web Connect branding.
    # INTU.BID is intentionally included because QuickBooks validates
    # Web Connect files against its Financial Institutions Directory.
    td_org = "TD Canada Trust"
    td_fid = "004"
    td_intu_bid = "0002"

    qbo = f"""OFXHEADER:100
DATA:OFXSGML
VERSION:102
SECURITY:NONE
ENCODING:USASCII
CHARSET:1252
COMPRESSION:NONE
OLDFILEUID:NONE
NEWFILEUID:NONE

<OFX>
<SIGNONMSGSRSV1>
<SONRS>
<STATUS>
<CODE>0
<SEVERITY>INFO
</STATUS>
<DTSERVER>{server_time}
<LANGUAGE>ENG
<FI>
<ORG>{td_org}
<FID>{td_fid}
</FI>
<INTU.BID>{td_intu_bid}
</SONRS>
</SIGNONMSGSRSV1>
<CREDITCARDMSGSRSV1>
<CCSTMTTRNRS>
<TRNUID>1
<STATUS>
<CODE>0
<SEVERITY>INFO
<MESSAGE>Success
</STATUS>
<CCSTMTRS>
<CURDEF>CAD
<CCACCTFROM>
<ACCTID>{account_id}
</CCACCTFROM>
<BANKTRANLIST>
<DTSTART>{start_date}
<DTEND>{end_date}
{transactions_text}
</BANKTRANLIST>
<LEDGERBAL>
<BALAMT>{ledger_balance:.2f}
<DTASOF>{end_date}
</LEDGERBAL>
</CCSTMTRS>
</CCSTMTTRNRS>
</CREDITCARDMSGSRSV1>
</OFX>
"""

    return qbo


# =========================================================
# USER INTERFACE
# =========================================================

# =========================================================
# BANK / ACCOUNT SELECTION
#
# IMPORTANT:
# Adding a bank to the dropdown does NOT activate a parser.
# Only combinations in SUPPORTED_COMBINATIONS can process
# statements. This protects the working TD logic.
# =========================================================

CANADIAN_BANKS = [
    "TD Canada Trust",
    "RBC Royal Bank",
    "Scotiabank",
    "BMO Bank of Montreal",
    "CIBC",
    "National Bank of Canada",
    "Desjardins",
    "Tangerine Bank",
    "Simplii Financial",
    "EQ Bank",
    "ATB Financial",
    "Laurentian Bank of Canada",
    "Canadian Western Bank",
    "Manulife Bank",
    "PC Financial",
    "Wealthsimple",
    "Motusbank",
    "Home Trust",
    "First Nations Bank of Canada",
    "Coast Capital Savings",
    "Meridian Credit Union",
    "Vancity",
    "Servus Credit Union",
    "Other Canadian Bank / Credit Union"
]

ACCOUNT_TYPES = [
    "Personal Chequing",
    "Business Chequing",
    "Personal Savings",
    "Business Savings",
    "Credit Card",
    "Line of Credit"
]

SUPPORTED_COMBINATIONS = {
    ("TD Canada Trust", "Business Chequing"),
    ("TD Canada Trust", "Credit Card")
}


col1, col2 = st.columns(2)

with col1:

    bank = st.selectbox(
        "Bank",
        CANADIAN_BANKS
    )

with col2:

    account_type = st.selectbox(
        "Account Type",
        ACCOUNT_TYPES,
        index=1
    )


is_supported = (
    bank,
    account_type
) in SUPPORTED_COMBINATIONS


if is_supported:

    st.success(
        f"Supported: {bank} - {account_type}"
    )

else:

    st.info(
        f"{bank} - {account_type} is listed but not activated yet. "
        "A sample PDF statement must be tested before this combination "
        "is enabled."
    )


uploaded_file = st.file_uploader(
    "Upload Bank PDF Statement",
    type=["pdf"]
)


if uploaded_file is not None:

    st.success(
        f"Uploaded: {uploaded_file.name}"
    )

    if st.button(
        "Process Statement",
        type="primary",
        disabled=not is_supported
    ):

        pdf_bytes = (
            uploaded_file.getvalue()
        )

        try:

            if (
                bank == "TD Canada Trust"
                and
                account_type == "Credit Card"
            ):

                df, statement_info = (
                    extract_td_credit_card_transactions(
                        pdf_bytes
                    )
                )

            elif (
                bank == "TD Canada Trust"
                and
                account_type == "Business Chequing"
            ):

                df, statement_info = (
                    extract_td_chequing_transactions(
                        pdf_bytes
                    )
                )

            else:

                st.error(
                    "This bank/account combination is not activated yet."
                )
                st.stop()

            st.session_state[
                "transactions"
            ] = df

            st.session_state[
                "statement_info"
            ] = statement_info

            st.session_state[
                "processed_bank"
            ] = bank

            st.session_state[
                "processed_account_type"
            ] = account_type

        except Exception as e:

            st.error(
                f"Unable to process statement: {e}"
            )


# =========================================================
# RESULTS
# =========================================================

if "transactions" in st.session_state:

    df = st.session_state[
        "transactions"
    ]

    statement_info = (
        st.session_state[
            "statement_info"
        ]
    )

    st.divider()

    st.header(
        "Transaction Review"
    )

    if df.empty:

        st.error(
            "No transactions were detected."
        )

    else:

        edited_df = st.data_editor(
            df,
            use_container_width=True,
            hide_index=True,
            num_rows="dynamic",
            column_config={

                "Date":
                    st.column_config.TextColumn(
                        "Date"
                    ),

                "Description":
                    st.column_config.TextColumn(
                        "Description"
                    ),

                "Debit":
                    st.column_config.NumberColumn(
                        "Debit",
                        format="$%.2f"
                    ),

                "Credit":
                    st.column_config.NumberColumn(
                        "Credit",
                        format="$%.2f"
                    )
            }
        )

        debit_total = round(
            float(
                edited_df[
                    "Debit"
                ].sum()
            ),
            2
        )

        credit_total = round(
            float(
                edited_df[
                    "Credit"
                ].sum()
            ),
            2
        )

        debit_count = int(
            (
                edited_df[
                    "Debit"
                ] > 0
            ).sum()
        )

        credit_count = int(
            (
                edited_df[
                    "Credit"
                ] > 0
            ).sum()
        )

        transaction_count = (
            len(edited_df)
        )

        st.divider()

        st.header(
            "Statement Control"
        )

        col1, col2, col3 = (
            st.columns(3)
        )

        col1.metric(
            "Transactions",
            transaction_count
        )

        col2.metric(
            "Total Debits",
            f"${debit_total:,.2f}"
        )

        col3.metric(
            "Total Credits",
            f"${credit_total:,.2f}"
        )

        st.write(
            f"Extracted Debits: "
            f"{debit_count} transactions"
        )

        st.write(
            f"Extracted Credits: "
            f"{credit_count} transactions"
        )

        reconciled = False


        # =================================================
        # CHEQUING RECONCILIATION
        # =================================================

        if (
            statement_info[
                "statement_type"
            ]
            == "chequing"
        ):

            controls = (
                statement_info[
                    "control"
                ]
            )

            st.divider()

            if (
                controls[
                    "debit_total"
                ]
                is not None
            ):

                st.write(
                    "TD Statement Debits: "
                    f"{controls['debit_count']} "
                    "transactions, "
                    f"${controls['debit_total']:,.2f}"
                )

            if (
                controls[
                    "credit_total"
                ]
                is not None
            ):

                st.write(
                    "TD Statement Credits: "
                    f"{controls['credit_count']} "
                    "transactions, "
                    f"${controls['credit_total']:,.2f}"
                )

            if (
                controls[
                    "debit_total"
                ]
                is not None
                and
                controls[
                    "credit_total"
                ]
                is not None
            ):

                reconciled = (

                    debit_count
                    ==
                    controls[
                        "debit_count"
                    ]

                    and

                    credit_count
                    ==
                    controls[
                        "credit_count"
                    ]

                    and

                    abs(
                        debit_total
                        -
                        controls[
                            "debit_total"
                        ]
                    )
                    < 0.01

                    and

                    abs(
                        credit_total
                        -
                        controls[
                            "credit_total"
                        ]
                    )
                    < 0.01
                )

            if reconciled:

                st.success(
                    "✓ STATEMENT RECONCILES"
                )

            else:

                st.error(
                    "STATEMENT DOES NOT RECONCILE"
                )


        # =================================================
        # CREDIT CARD RECONCILIATION
        # =================================================

        else:

            summary = (
                statement_info[
                    "summary"
                ]
            )

            st.divider()

            previous_balance = (
                summary.get(
                    "previous_balance"
                )
            )

            purchases = (
                summary.get(
                    "purchases_charges"
                )
            )

            interest = (
                summary.get(
                    "interest"
                )
                or 0.0
            )

            fees = (
                summary.get(
                    "fees"
                )
                or 0.0
            )

            payments = (
                summary.get(
                    "payments_credits"
                )
            )

            new_balance = (
                summary.get(
                    "new_balance"
                )
            )

            if previous_balance is not None:

                st.write(
                    "TD Previous Balance: "
                    f"${previous_balance:,.2f}"
                )

            if purchases is not None:

                st.write(
                    "TD Purchases & Other Charges: "
                    f"${purchases:,.2f}"
                )

            st.write(
                "TD Interest: "
                f"${interest:,.2f}"
            )

            st.write(
                "TD Fees: "
                f"${fees:,.2f}"
            )

            if payments is not None:

                st.write(
                    "TD Payments & Credits: "
                    f"${payments:,.2f}"
                )

            if new_balance is not None:

                st.write(
                    "TD New Balance: "
                    f"${new_balance:,.2f}"
                )

            expected_charges = (
                (purchases or 0.0)
                +
                interest
                +
                fees
            )

            charges_match = (
                abs(
                    debit_total
                    -
                    expected_charges
                )
                < 0.01
            )

            payments_match = (
                payments is not None
                and
                abs(
                    credit_total
                    -
                    payments
                )
                < 0.01
            )

            statement_math_match = False

            if (
                previous_balance is not None
                and
                payments is not None
                and
                purchases is not None
                and
                new_balance is not None
            ):

                calculated_new_balance = (

                    previous_balance

                    -

                    payments

                    +

                    purchases

                    +

                    interest

                    +

                    fees
                )

                statement_math_match = (
                    abs(
                        calculated_new_balance
                        -
                        new_balance
                    )
                    < 0.01
                )

            reconciled = (
                charges_match
                and
                payments_match
                and
                statement_math_match
            )

            if reconciled:

                st.success(
                    "✓ CREDIT CARD STATEMENT RECONCILES"
                )

            else:

                st.error(
                    "CREDIT CARD STATEMENT "
                    "DOES NOT RECONCILE"
                )

                st.write(
                    "Expected Charges: "
                    f"${expected_charges:,.2f}"
                )

                st.write(
                    "Extracted Charges: "
                    f"${debit_total:,.2f}"
                )

                if payments is not None:

                    st.write(
                        "Expected Payments/Credits: "
                        f"${payments:,.2f}"
                    )

                    st.write(
                        "Extracted Payments/Credits: "
                        f"${credit_total:,.2f}"
                    )


        # =================================================
        # DOWNLOADS
        # =================================================

        st.divider()

        st.header(
            "Download QuickBooks Files"
        )

        if reconciled:

            st.success(
                "Statement verified. "
                "Choose your QuickBooks format."
            )

            csv_data = (
                generate_quickbooks_csv(
                    edited_df
                )
            )

            if (
                statement_info[
                    "statement_type"
                ]
                == "chequing"
            ):

                qbo_data = (
                    generate_td_chequing_qbo(
                        edited_df,
                        statement_info[
                            "account_id"
                        ]
                    )
                )

            else:

                qbo_data = (
                    generate_td_credit_card_qbo(
                        edited_df,
                        statement_info[
                            "account_id"
                        ],
                        statement_info[
                            "summary"
                        ].get(
                            "new_balance"
                        )
                    )
                )

            col1, col2 = (
                st.columns(2)
            )

            with col1:

                st.download_button(
                    label=(
                        "Download QuickBooks CSV"
                    ),
                    data=csv_data,
                    file_name=(
                        "quickbooks_transactions.csv"
                    ),
                    mime="text/csv",
                    use_container_width=True
                )

            with col2:

                st.download_button(
                    label=(
                        "Download QuickBooks QBO"
                    ),
                    data=qbo_data.encode(
                        "cp1252",
                        errors="replace"
                    ),
                    file_name=(
                        "quickbooks_webconnect.qbo"
                    ),
                    mime="application/x-ofx",
                    use_container_width=True
                )

        else:

            st.warning(
                "Downloads are disabled until "
                "the statement reconciles."
            )


# =========================================================
# FOOTER
# =========================================================

st.divider()

st.caption(
    "Tax Square Professional Corporation"
)
