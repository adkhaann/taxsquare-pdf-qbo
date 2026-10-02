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
    "Convert TD bank and credit-card PDF statements into "
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

    return text.strip()[:255]


def td_qbo_datetime(date_object):

    return (
        date_object.strftime("%Y%m%d")
        + "020000[-5:EST]"
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

    return str(
        int(digest[:14], 16)
    )


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

    lines = text.splitlines()

    candidates = []

    for line in lines:

        match = re.search(
            r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|"
            r"SEP|OCT|NOV|DEC)"
            r"\d{2}\s+"
            r"([\d,]+\.\d{2})"
            r"(OD)?\s*$",
            line.strip(),
            re.IGNORECASE
        )

        if match:

            amount = clean_amount(
                match.group(2)
            )

            if match.group(3):
                amount = -amount

            candidates.append(
                amount
            )

    if candidates:
        return candidates[-1]

    return None


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
#
# THIS IS THE WORKING VERSION BASED ON THE ACTUAL
# TD CHEQUING PDF COLUMN POSITIONS.
# =========================================================

def extract_td_chequing_transactions(
    pdf_bytes
):

    doc = fitz.open(
        stream=pdf_bytes,
        filetype="pdf"
    )

    full_text = ""

    transactions = []

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

    ending_balance = (
        get_chequing_ending_balance(
            full_text
        )
    )

    account_id = (
        get_chequing_account_id(
            full_text
        )
    )

    for page in doc:

        words = page.get_text("words")

        if not words:
            continue

        page_width = page.rect.width

        # -------------------------------------------------
        # These are the working TD chequing column zones.
        # -------------------------------------------------

        debit_left = (
            page_width * 0.31
        )

        debit_right = (
            page_width * 0.47
        )

        credit_left = (
            page_width * 0.47
        )

        credit_right = (
            page_width * 0.63
        )

        description_right = (
            debit_left
        )

        # -------------------------------------------------
        # Find transaction dates
        # -------------------------------------------------

        date_words = []

        for word in words:

            x0, y0, x1, y1, text = (
                word[:5]
            )

            cleaned = (
                text.strip().upper()
            )

            if re.fullmatch(
                r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|"
                r"SEP|OCT|NOV|DEC)\d{2}",
                cleaned
            ):

                date_words.append(
                    word
                )

        # -------------------------------------------------
        # Process each transaction row
        # -------------------------------------------------

        for date_word in date_words:

            (
                dx0,
                dy0,
                dx1,
                dy1,
                date_text
            ) = date_word[:5]

            date_center_y = (
                dy0 + dy1
            ) / 2

            row_words = []

            for word in words:

                x0, y0, x1, y1, text = (
                    word[:5]
                )

                center_y = (
                    y0 + y1
                ) / 2

                if abs(
                    center_y
                    -
                    date_center_y
                ) <= 3.5:

                    row_words.append(
                        word
                    )

            if not row_words:
                continue

            row_words.sort(
                key=lambda item: item[0]
            )

            # -------------------------------------------------
            # DESCRIPTION
            # -------------------------------------------------

            description_parts = []

            for word in row_words:

                x0, y0, x1, y1, text = (
                    word[:5]
                )

                if x0 < description_right:

                    description_parts.append(
                        text
                    )

            description = " ".join(
                description_parts
            ).strip()

            description = (
                description
                .replace(
                    date_text,
                    ""
                )
                .strip()
            )

            if not description:
                continue

            skip_phrases = [
                "BALANCE FORWARD",
                "DESCRIPTION",
                "CREDITS",
                "DEBITS",
                "NEXT STATEMENT",
                "MONTHLY AVER",
                "MONTHLY MIN",
                "DEP CONTENT",
                "BUSINESS LINE OF CREDIT LIMIT"
            ]

            if any(
                phrase in description.upper()
                for phrase in skip_phrases
            ):
                continue

            # -------------------------------------------------
            # DEBIT / CREDIT
            # -------------------------------------------------

            debit = 0.0
            credit = 0.0

            for word in row_words:

                x0, y0, x1, y1, text = (
                    word[:5]
                )

                cleaned = (
                    text
                    .replace(",", "")
                    .replace("$", "")
                    .strip()
                )

                if not re.fullmatch(
                    r"\d+\.\d{2}",
                    cleaned
                ):
                    continue

                amount = clean_amount(
                    cleaned
                )

                center_x = (
                    x0 + x1
                ) / 2

                if (
                    debit_left
                    <= center_x
                    < debit_right
                ):

                    debit = amount

                elif (
                    credit_left
                    <= center_x
                    < credit_right
                ):

                    credit = amount

            if (
                debit == 0
                and
                credit == 0
            ):
                continue

            transaction_date = (
                parse_chequing_date(
                    date_text,
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
        "ending_balance": ending_balance,
        "account_id": account_id
    }

    return df, statement_info


# =========================================================
# TD CREDIT CARD SUMMARY
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

    # -----------------------------------------------------
    # First try direct text patterns
    # -----------------------------------------------------

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

    return summary


# =========================================================
# TD CREDIT CARD ACCOUNT ID
# =========================================================

def get_credit_card_account_id(
    text
):

    patterns = [
        r"Account\s+Number.*?(\d{4})\b",
        r"\*{2,}\s*(\d{4})\b",
        r"ending\s+in\s+(\d{4})"
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
# TD CREDIT CARD YEAR
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


# =========================================================
# TD CREDIT CARD PARSER
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

    # -----------------------------------------------------
    # Read actual TD credit-card transaction coordinates
    # -----------------------------------------------------

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

            # Transaction month column

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

            # -------------------------------------------------
            # DAY
            # -------------------------------------------------

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

            # -------------------------------------------------
            # AMOUNT
            # -------------------------------------------------

            amount_text = None

            for word in row_words:

                wx0, wy0, wx1, wy1, text = (
                    word[:5]
                )

                cleaned = (
                    text.strip()
                )

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

            # -------------------------------------------------
            # DESCRIPTION
            # -------------------------------------------------

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

            # -------------------------------------------------
            # AMOUNT DIRECTION
            # -------------------------------------------------

            numeric_amount = (
                clean_amount(
                    amount_text
                )
            )

            debit = 0.0
            credit = 0.0

            # Positive on TD credit card = charge
            # Negative = payment / credit

            if numeric_amount < 0:

                credit = abs(
                    numeric_amount
                )

            else:

                debit = numeric_amount

            # -------------------------------------------------
            # DATE
            # -------------------------------------------------

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

    # -----------------------------------------------------
    # FALLBACK SUMMARY CALCULATION
    #
    # The TD PDF sometimes splits "Purchases & Other
    # Charges" and its amount into separate PDF blocks.
    #
    # If that control figure cannot be read directly,
    # derive it from the statement equation:
    #
    # Previous Balance
    # - Payments/Credits
    # + Purchases
    # + Interest
    # + Fees
    # = New Balance
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

        calculated_purchases = (
            summary["new_balance"]
            -
            summary["previous_balance"]
            +
            summary["payments_credits"]
            -
            interest
            -
            fees
        )

        summary[
            "purchases_charges"
        ] = round(
            calculated_purchases,
            2
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

def generate_quickbooks_csv(df):

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
# TD CHEQUING QBO
#
# PRESERVES THE STRUCTURE THAT SUCCESSFULLY IMPORTED
# INTO QUICKBOOKS DESKTOP.
# =========================================================

def generate_td_chequing_qbo(
    df,
    account_id,
    ending_balance
):

    working_df = df.copy()

    working_df["DateObject"] = (
        pd.to_datetime(
            working_df["Date"]
        )
    )

    first_date = (
        working_df[
            "DateObject"
        ].min()
    )

    last_date = (
        working_df[
            "DateObject"
        ].max()
    )

    start_date = (
        first_date.strftime(
            "%Y%m%d"
        )
    )

    end_date = (
        td_qbo_datetime(
            last_date
        )
    )

    server_time = (
        datetime.now()
        .strftime(
            "%Y%m%d%H%M%S"
        )
        +
        "[-5:EST]"
    )

    transaction_blocks = []

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

        posted_date = (
            td_qbo_datetime(
                date_object
            )
        )

        description = (
            clean_qbo_text(
                row["Description"]
            )
        )

        transaction_type = (
            "DEBIT"
            if amount < 0
            else "CREDIT"
        )

        duplicate_key = (
            date_text,
            description,
            f"{amount:.2f}"
        )

        duplicate_counter[
            duplicate_key
        ] = (
            duplicate_counter.get(
                duplicate_key,
                0
            )
            + 1
        )

        occurrence = (
            duplicate_counter[
                duplicate_key
            ]
        )

        fitid = create_fitid(
            "TD-BANK",
            date_text,
            description,
            amount,
            occurrence
        )

        transaction_blocks.append(
            "<STMTTRN>\n"
            f"<TRNTYPE>{transaction_type}\n"
            f"<DTPOSTED>{posted_date}\n"
            f"<TRNAMT>{amount:.2f}\n"
            f"<FITID>{fitid}\n"
            f"<NAME>{description}\n"
            "</STMTTRN>"
        )

    transactions_text = "\n".join(
        transaction_blocks
    )

    if ending_balance is None:
        ending_balance = 0.00

    trnuid = (
        "QWEB - "
        +
        datetime.now().strftime(
            "%Y%m%d%H%M%S"
        )
        +
        "0191"
    )

    return f"""OFXHEADER:100
DATA:OFXSGML
VERSION:102
SECURITY:TYPE1
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
<MESSAGE>OK
</STATUS>
<DTSERVER>{server_time}
<USERKEY>--NoUserKey--
<LANGUAGE>ENG
<INTU.BID>00002
</SONRS>
</SIGNONMSGSRSV1>
<BANKMSGSRSV1>
<STMTTRNRS>
<TRNUID>{trnuid}
<STATUS>
<CODE>0
<SEVERITY>INFO
<MESSAGE>OK
</STATUS>
<STMTRS>
<CURDEF>CAD
<BANKACCTFROM>
<BANKID>300000100
<ACCTID>{account_id}
<ACCTTYPE>CHECKING
</BANKACCTFROM>
<BANKTRANLIST>
<DTSTART>{start_date}
<DTEND>{end_date}
{transactions_text}
</BANKTRANLIST>
<LEDGERBAL>
<BALAMT>{ending_balance:.2f}
<DTASOF>{end_date}
</LEDGERBAL>
</STMTRS>
</STMTTRNRS>
</BANKMSGSRSV1>
</OFX>
"""


# =========================================================
# TD CREDIT CARD QBO
# =========================================================

def generate_td_credit_card_qbo(
    df,
    account_id,
    new_balance
):

    working_df = df.copy()

    working_df["DateObject"] = (
        pd.to_datetime(
            working_df["Date"]
        )
    )

    first_date = (
        working_df[
            "DateObject"
        ].min()
    )

    last_date = (
        working_df[
            "DateObject"
        ].max()
    )

    start_date = (
        first_date.strftime(
            "%Y%m%d"
        )
    )

    end_date = (
        td_qbo_datetime(
            last_date
        )
    )

    server_time = (
        datetime.now()
        .strftime(
            "%Y%m%d%H%M%S"
        )
        +
        "[-5:EST]"
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

        # Purchase = negative
        # Payment/refund = positive

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

        posted_date = (
            td_qbo_datetime(
                date_object
            )
        )

        description = (
            clean_qbo_text(
                row["Description"]
            )
        )

        transaction_type = (
            "DEBIT"
            if amount < 0
            else "CREDIT"
        )

        duplicate_key = (
            date_text,
            description,
            f"{amount:.2f}"
        )

        duplicate_counter[
            duplicate_key
        ] = (
            duplicate_counter.get(
                duplicate_key,
                0
            )
            + 1
        )

        occurrence = (
            duplicate_counter[
                duplicate_key
            ]
        )

        fitid = create_fitid(
            "TD-CC",
            date_text,
            description,
            amount,
            occurrence
        )

        blocks.append(
            "<STMTTRN>\n"
            f"<TRNTYPE>{transaction_type}\n"
            f"<DTPOSTED>{posted_date}\n"
            f"<TRNAMT>{amount:.2f}\n"
            f"<FITID>{fitid}\n"
            f"<NAME>{description}\n"
            "</STMTTRN>"
        )

    transactions_text = "\n".join(
        blocks
    )

    if new_balance is None:

        ledger_balance = 0.00

    else:

        ledger_balance = -abs(
            float(new_balance)
        )

    trnuid = (
        "QWEB - "
        +
        datetime.now().strftime(
            "%Y%m%d%H%M%S"
        )
        +
        "0191"
    )

    return f"""OFXHEADER:100
DATA:OFXSGML
VERSION:102
SECURITY:TYPE1
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
<MESSAGE>OK
</STATUS>
<DTSERVER>{server_time}
<USERKEY>--NoUserKey--
<LANGUAGE>ENG
<INTU.BID>00002
</SONRS>
</SIGNONMSGSRSV1>
<CREDITCARDMSGSRSV1>
<CCSTMTTRNRS>
<TRNUID>{trnuid}
<STATUS>
<CODE>0
<SEVERITY>INFO
<MESSAGE>OK
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


# =========================================================
# USER CONTROLS
# =========================================================

col1, col2 = st.columns(2)

with col1:

    bank = st.selectbox(
        "Bank",
        [
            "TD Canada Trust"
        ]
    )

with col2:

    account_type = st.selectbox(
        "Account Type",
        [
            "Business Chequing",
            "Credit Card"
        ]
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
        type="primary"
    ):

        pdf_bytes = (
            uploaded_file.getvalue()
        )

        try:

            if (
                account_type
                == "Credit Card"
            ):

                df, statement_info = (
                    extract_td_credit_card_transactions(
                        pdf_bytes
                    )
                )

            else:

                df, statement_info = (
                    extract_td_chequing_transactions(
                        pdf_bytes
                    )
                )

            st.session_state[
                "transactions"
            ] = df

            st.session_state[
                "statement_info"
            ] = statement_info

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

        # =================================================
        # STATEMENT CONTROL
        # =================================================

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
        # CHEQUING CONTROL
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
        # CREDIT CARD CONTROL
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

            # -------------------------------------------------
            # Expected extracted charges:
            #
            # Purchases & Other Charges
            # + Interest
            # + Fees
            # -------------------------------------------------

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

            # -------------------------------------------------
            # Also verify statement equation
            # -------------------------------------------------

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
                        ],
                        statement_info[
                            "ending_balance"
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
                    data=qbo_data,
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
