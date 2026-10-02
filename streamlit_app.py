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

def money_to_float(value):

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


def create_fitid(prefix, date_text, description, amount, occurrence):

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


def td_qbo_datetime(date_object):

    return (
        date_object.strftime("%Y%m%d")
        + "020000[-5:EST]"
    )


# =========================================================
# TD CHEQUING HELPERS
# =========================================================

def parse_td_chequing_date(date_text, statement_year):

    try:

        parsed = datetime.strptime(
            f"{date_text.strip().upper()}{statement_year}",
            "%b%d%Y"
        )

        return parsed.strftime("%Y-%m-%d")

    except:
        return date_text


def get_chequing_statement_year(text):

    match = re.search(
        r"(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)"
        r"\s+\d{1,2}/(\d{2})",
        text,
        re.IGNORECASE
    )

    if match:
        return 2000 + int(match.group(1))

    return datetime.now().year


def get_chequing_control_totals(text):

    credit_count = None
    credit_total = None

    debit_count = None
    debit_total = None

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

    if credit_match:

        credit_count = int(
            credit_match.group(1)
        )

        credit_total = money_to_float(
            credit_match.group(2)
        )

    if debit_match:

        debit_count = int(
            debit_match.group(1)
        )

        debit_total = money_to_float(
            debit_match.group(2)
        )

    return {
        "credit_count": credit_count,
        "credit_total": credit_total,
        "debit_count": debit_count,
        "debit_total": debit_total
    }


def get_td_chequing_ending_balance(text):

    lines = text.splitlines()

    candidates = []

    for line in lines:

        match = re.search(
            r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)"
            r"\d{2}\s+"
            r"([\d,]+\.\d{2})"
            r"(OD)?\s*$",
            line.strip(),
            re.IGNORECASE
        )

        if match:

            amount = money_to_float(
                match.group(2)
            )

            if match.group(3):
                amount = -amount

            candidates.append(amount)

    if candidates:
        return candidates[-1]

    return None


def get_td_chequing_account_id(text):

    match = re.search(
        r"\b\d{4}\s+\d{4}-(\d{7})\b",
        text
    )

    if match:
        return match.group(1)

    return "5263645"


# =========================================================
# TD CHEQUING PARSER
# KEEP THIS LOGIC SEPARATE FROM CREDIT CARD
# =========================================================

def extract_td_chequing_transactions(pdf_bytes):

    doc = fitz.open(
        stream=pdf_bytes,
        filetype="pdf"
    )

    transactions = []

    full_text = ""

    for page in doc:
        full_text += page.get_text("text") + "\n"

    statement_year = get_chequing_statement_year(
        full_text
    )

    control = get_chequing_control_totals(
        full_text
    )

    ending_balance = get_td_chequing_ending_balance(
        full_text
    )

    account_id = get_td_chequing_account_id(
        full_text
    )

    for page in doc:

        words = page.get_text("words")

        if not words:
            continue

        page_width = page.rect.width

        debit_left = page_width * 0.31
        debit_right = page_width * 0.47

        credit_left = page_width * 0.47
        credit_right = page_width * 0.63

        description_right = debit_left

        date_words = []

        for word in words:

            x0, y0, x1, y1, text, block, line, word_no = word

            cleaned = text.strip().upper()

            if re.fullmatch(
                r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2}",
                cleaned
            ):

                date_words.append(word)

        for date_word in date_words:

            (
                dx0,
                dy0,
                dx1,
                dy1,
                date_text,
                _,
                _,
                _
            ) = date_word

            row_words = []

            tolerance = 3.5

            date_center_y = (
                dy0 + dy1
            ) / 2

            for word in words:

                (
                    x0,
                    y0,
                    x1,
                    y1,
                    text,
                    block,
                    line,
                    word_no
                ) = word

                center_y = (
                    y0 + y1
                ) / 2

                if abs(
                    center_y - date_center_y
                ) <= tolerance:

                    row_words.append(word)

            if not row_words:
                continue

            row_words.sort(
                key=lambda w: w[0]
            )

            description_parts = []

            for word in row_words:

                x0, y0, x1, y1, text, *_ = word

                if x0 < description_right:
                    description_parts.append(text)

            description = " ".join(
                description_parts
            ).strip()

            description = description.replace(
                date_text,
                ""
            ).strip()

            upper_description = (
                description.upper()
            )

            skip_phrases = [
                "BALANCE FORWARD",
                "NEXT STATEMENT",
                "MONTHLY AVER",
                "MONTHLY MIN",
                "DEP CONTENT",
                "BUSINESS LINE OF CREDIT LIMIT"
            ]

            if any(
                phrase in upper_description
                for phrase in skip_phrases
            ):
                continue

            if description == "":
                continue

            debit = 0.0
            credit = 0.0

            for word in row_words:

                x0, y0, x1, y1, text, *_ = word

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

                amount = money_to_float(
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

            if debit == 0 and credit == 0:
                continue

            formatted_date = parse_td_chequing_date(
                date_text,
                statement_year
            )

            transactions.append({
                "Date": formatted_date,
                "Description": description,
                "Debit": debit,
                "Credit": credit
            })

    doc.close()

    df = pd.DataFrame(transactions)

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
        "control": control,
        "ending_balance": ending_balance,
        "account_id": account_id,
        "statement_type": "chequing"
    }

    return df, statement_info


# =========================================================
# TD CREDIT CARD HELPERS
# =========================================================

def get_credit_card_year(text):

    # Look for statement period ending date first

    patterns = [
        r"Statement\s+Period.*?"
        r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)"
        r"\s+\d{1,2},?\s+(20\d{2})",

        r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)"
        r"\s+\d{1,2},\s+(20\d{2})"
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE | re.DOTALL
        )

        if match:

            if len(match.groups()) >= 2:
                return int(match.group(2))

    # Uploaded statement is 2026, but don't hard-code
    # unless no year can be extracted.

    year_match = re.search(
        r"\b(20\d{2})\b",
        text
    )

    if year_match:
        return int(year_match.group(1))

    return datetime.now().year


def parse_credit_card_date(month, day, year):

    try:

        parsed = datetime.strptime(
            f"{month} {day} {year}",
            "%b %d %Y"
        )

        return parsed.strftime("%Y-%m-%d")

    except:
        return f"{month} {day}"


def get_credit_card_summary(text):

    """
    Extract TD credit-card statement summary.

    We use these figures for reconciliation instead of
    trying to force bank-style debit/credit controls.
    """

    summary = {
        "previous_balance": None,
        "payments_credits": None,
        "purchases_charges": None,
        "interest": None,
        "new_balance": None
    }

    patterns = {

        "previous_balance": [
            r"Previous\s+Balance\s+\$?\s*([\d,]+\.\d{2})"
        ],

        "payments_credits": [
            r"Payments\s*(?:&|and)\s*Credits\s+"
            r"\$?\s*([\d,]+\.\d{2})"
        ],

        "purchases_charges": [
            r"Purchases\s*(?:&|and)\s*Other\s*Charges\s+"
            r"\$?\s*([\d,]+\.\d{2})",

            r"Purchases\s+and\s+Other\s+Charges\s+"
            r"\$?\s*([\d,]+\.\d{2})"
        ],

        "interest": [
            r"Interest\s+Charged\s+\$?\s*([\d,]+\.\d{2})",
            r"Interest\s+\$?\s*([\d,]+\.\d{2})"
        ],

        "new_balance": [
            r"New\s+Balance\s+\$?\s*([\d,]+\.\d{2})"
        ]
    }

    for key, pattern_list in patterns.items():

        for pattern in pattern_list:

            match = re.search(
                pattern,
                text,
                re.IGNORECASE
            )

            if match:

                summary[key] = money_to_float(
                    match.group(1)
                )

                break

    return summary


def get_credit_card_account_id(text):

    """
    Try to obtain the last four digits displayed
    on the statement.
    """

    patterns = [
        r"(?:Account|Card).*?(\d{4})\b",
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

    return "1674"


# =========================================================
# TD CREDIT CARD PARSER
# =========================================================

def extract_td_credit_card_transactions(pdf_bytes):

    doc = fitz.open(
        stream=pdf_bytes,
        filetype="pdf"
    )

    full_text = ""

    for page in doc:
        full_text += page.get_text("text") + "\n"

    statement_year = get_credit_card_year(
        full_text
    )

    summary = get_credit_card_summary(
        full_text
    )

    account_id = get_credit_card_account_id(
        full_text
    )

    transactions = []

    # -----------------------------------------------------
    # Credit-card transaction rows are handled separately
    # from chequing.
    #
    # We use PyMuPDF line/block positioning rather than
    # chequing debit/credit columns.
    # -----------------------------------------------------

    month_pattern = (
        r"JAN|FEB|MAR|APR|MAY|JUN|JUL|"
        r"AUG|SEP|OCT|NOV|DEC"
    )

    amount_pattern = re.compile(
        r"^-?\$?[\d,]+\.\d{2}(?:CR)?$",
        re.IGNORECASE
    )

    for page in doc:

        words = page.get_text("words")

        if not words:
            continue

        # Group words by visual line

        line_groups = {}

        for word in words:

            x0, y0, x1, y1, text, block, line, word_no = word

            key = (
                block,
                line
            )

            line_groups.setdefault(
                key,
                []
            ).append(word)

        ordered_lines = []

        for key, line_words in line_groups.items():

            line_words = sorted(
                line_words,
                key=lambda w: w[0]
            )

            y_position = min(
                w[1] for w in line_words
            )

            ordered_lines.append(
                (
                    y_position,
                    line_words
                )
            )

        ordered_lines.sort(
            key=lambda item: item[0]
        )

        for _, line_words in ordered_lines:

            texts = [
                w[4].strip()
                for w in line_words
                if w[4].strip()
            ]

            if len(texts) < 3:
                continue

            line_text = " ".join(texts)

            upper_line = line_text.upper()

            # Ignore headings and summary rows

            skip_phrases = [
                "TRANSACTION DATE",
                "POSTING DATE",
                "DESCRIPTION",
                "AMOUNT",
                "PREVIOUS BALANCE",
                "NEW BALANCE",
                "TOTAL",
                "CREDIT LIMIT",
                "AVAILABLE CREDIT",
                "MINIMUM PAYMENT",
                "PAYMENT DUE DATE"
            ]

            if any(
                phrase in upper_line
                for phrase in skip_phrases
            ):
                continue

            # ---------------------------------------------
            # Find first transaction date
            # ---------------------------------------------

            transaction_month = None
            transaction_day = None
            date_end_index = None

            # Formats can appear as:
            # JUN 10
            # JUN10

            for i in range(len(texts)):

                token = texts[i].upper()

                combined_match = re.fullmatch(
                    rf"({month_pattern})(\d{{1,2}})",
                    token
                )

                if combined_match:

                    transaction_month = (
                        combined_match.group(1)
                    )

                    transaction_day = int(
                        combined_match.group(2)
                    )

                    date_end_index = i

                    break

                if re.fullmatch(
                    rf"({month_pattern})",
                    token
                ):

                    if (
                        i + 1 < len(texts)
                        and
                        re.fullmatch(
                            r"\d{1,2}",
                            texts[i + 1]
                        )
                    ):

                        transaction_month = token

                        transaction_day = int(
                            texts[i + 1]
                        )

                        date_end_index = i + 1

                        break

            if transaction_month is None:
                continue

            # ---------------------------------------------
            # Find amount at end of row
            # ---------------------------------------------

            amount_index = None
            amount_text = None

            for i in range(
                len(texts) - 1,
                -1,
                -1
            ):

                candidate = (
                    texts[i]
                    .replace(" ", "")
                )

                if amount_pattern.fullmatch(
                    candidate
                ):

                    amount_index = i
                    amount_text = candidate

                    break

            if amount_index is None:
                continue

            # ---------------------------------------------
            # Determine credit/payment versus charge
            # ---------------------------------------------

            is_credit = False

            if amount_text.upper().endswith("CR"):

                is_credit = True

                amount_text = (
                    amount_text[:-2]
                )

            amount = abs(
                money_to_float(
                    amount_text
                )
            )

            # Some PDF extraction places CR as separate word

            if (
                amount_index + 1
                < len(texts)
                and
                texts[amount_index + 1].upper()
                == "CR"
            ):

                is_credit = True

            # TD payment descriptions are also credits

            # We only use this as a fallback if the PDF
            # does not expose the CR marker.

            description_zone = texts[
                date_end_index + 1:
                amount_index
            ]

            # Remove posting date if present.
            # Usually the second date follows transaction date.

            description_parts = []

            i = 0

            while i < len(description_zone):

                token = description_zone[i]

                # Skip second date in form JUN 11

                if (
                    re.fullmatch(
                        rf"({month_pattern})",
                        token.upper()
                    )
                    and
                    i + 1 < len(description_zone)
                    and
                    re.fullmatch(
                        r"\d{1,2}",
                        description_zone[i + 1]
                    )
                ):

                    i += 2
                    continue

                # Skip combined second date JUN11

                if re.fullmatch(
                    rf"({month_pattern})\d{{1,2}}",
                    token.upper()
                ):

                    i += 1
                    continue

                description_parts.append(
                    token
                )

                i += 1

            description = " ".join(
                description_parts
            ).strip()

            if not description:
                continue

            upper_description = (
                description.upper()
            )

            if (
                "PAYMENT" in upper_description
                or
                "THANK YOU" in upper_description
            ):

                is_credit = True

            # ---------------------------------------------
            # Debit / Credit representation for app
            #
            # Debit = purchase/charge
            # Credit = payment/refund
            # ---------------------------------------------

            debit = 0.0
            credit = 0.0

            if is_credit:
                credit = amount
            else:
                debit = amount

            transaction_date = parse_credit_card_date(
                transaction_month,
                transaction_day,
                statement_year
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

        # Remove exact duplicate extraction rows

        df = (
            df
            .drop_duplicates()
            .reset_index(drop=True)
        )

    statement_info = {
        "summary": summary,
        "account_id": account_id,
        "statement_type": "credit_card"
    }

    return df, statement_info


# =========================================================
# QUICKBOOKS ONLINE CSV
# =========================================================

def generate_qbo_online_csv(
    df,
    statement_type
):

    export_df = df.copy()

    if statement_type == "chequing":

        # Bank:
        # deposit = positive
        # payment = negative

        export_df["Amount"] = (
            export_df["Credit"]
            -
            export_df["Debit"]
        )

    else:

        # Credit card:
        # purchase/charge = negative
        # payment/refund = positive
        #
        # This mirrors TD's genuine credit-card QBO.

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
    ].copy()

    export_df["Date"] = pd.to_datetime(
        export_df["Date"]
    ).dt.strftime("%m/%d/%Y")

    return export_df.to_csv(
        index=False
    )


# =========================================================
# TD CHEQUING DESKTOP QBO
# =========================================================

def generate_td_chequing_qbo(
    df,
    account_id,
    ending_balance
):

    working_df = df.copy()

    working_df["DateObject"] = pd.to_datetime(
        working_df["Date"]
    )

    first_date = working_df[
        "DateObject"
    ].min()

    last_date = working_df[
        "DateObject"
    ].max()

    start_date = (
        first_date.strftime("%Y%m%d")
    )

    end_date = td_qbo_datetime(
        last_date
    )

    server_time = (
        datetime.now()
        .strftime("%Y%m%d%H%M%S")
        + "[-5:EST]"
    )

    blocks = []

    duplicate_counter = {}

    for _, row in working_df.iterrows():

        debit = float(row["Debit"])
        credit = float(row["Credit"])

        amount = credit - debit

        date_object = row["DateObject"]

        date_text = (
            date_object.strftime("%Y%m%d")
        )

        posted_date = td_qbo_datetime(
            date_object
        )

        description = clean_qbo_text(
            row["Description"]
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
            ) + 1
        )

        occurrence = duplicate_counter[
            duplicate_key
        ]

        fitid = create_fitid(
            "TD-BANK",
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

    if ending_balance is None:
        ending_balance = 0.00

    trnuid = (
        "QWEB - "
        + datetime.now().strftime(
            "%Y%m%d%H%M%S"
        )
        + "0191"
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
# TD CREDIT CARD DESKTOP QBO
# =========================================================

def generate_td_credit_card_qbo(
    df,
    account_id,
    new_balance
):

    working_df = df.copy()

    working_df["DateObject"] = pd.to_datetime(
        working_df["Date"]
    )

    first_date = working_df[
        "DateObject"
    ].min()

    last_date = working_df[
        "DateObject"
    ].max()

    start_date = (
        first_date.strftime("%Y%m%d")
    )

    end_date = td_qbo_datetime(
        last_date
    )

    server_time = (
        datetime.now()
        .strftime("%Y%m%d%H%M%S")
        + "[-5:EST]"
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

        # TD genuine credit-card QBO:
        #
        # purchase = negative
        # payment/refund = positive

        amount = credit - debit

        date_object = row[
            "DateObject"
        ]

        date_text = (
            date_object.strftime(
                "%Y%m%d"
            )
        )

        posted_date = td_qbo_datetime(
            date_object
        )

        description = clean_qbo_text(
            row["Description"]
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
            ) + 1
        )

        occurrence = duplicate_counter[
            duplicate_key
        ]

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

    # Credit-card liability balance must be negative
    # in TD's genuine QBO representation.

    if new_balance is None:
        ledger_balance = 0.00
    else:
        ledger_balance = -abs(
            float(new_balance)
        )

    trnuid = (
        "QWEB - "
        + datetime.now().strftime(
            "%Y%m%d%H%M%S"
        )
        + "0191"
    )

    # TD credit-card Web Connect uses
    # CREDITCARDMSGSRSV1 / CCSTMTRS / CCACCTFROM.

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
            "Select Bank",
            "TD Canada Trust"
        ]
    )


with col2:

    account_type = st.selectbox(
        "Account Type",
        [
            "Business Chequing",
            "Personal Chequing",
            "Savings",
            "Credit Card"
        ]
    )


# =========================================================
# FILE UPLOAD
# =========================================================

uploaded_file = st.file_uploader(
    "Upload Bank PDF Statement",
    type=["pdf"]
)


if uploaded_file is not None:

    st.success(
        f"Uploaded: {uploaded_file.name}"
    )

    if bank != "TD Canada Trust":

        st.warning(
            "Please select TD Canada Trust."
        )

    elif account_type in [
        "Personal Chequing",
        "Savings"
    ]:

        st.warning(
            "This account type has not yet been configured."
        )

    else:

        if st.button(
            "Process Statement",
            type="primary"
        ):

            pdf_bytes = (
                uploaded_file.getvalue()
            )

            try:

                if account_type == "Credit Card":

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

    statement_info = st.session_state[
        "statement_info"
    ]

    processed_account_type = (
        st.session_state.get(
            "processed_account_type",
            ""
        )
    )

    st.divider()

    st.subheader(
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

        debit_total = float(
            edited_df["Debit"].sum()
        )

        credit_total = float(
            edited_df["Credit"].sum()
        )

        debit_count = int(
            (
                edited_df["Debit"] > 0
            ).sum()
        )

        credit_count = int(
            (
                edited_df["Credit"] > 0
            ).sum()
        )

        transaction_count = len(
            edited_df
        )

        st.divider()

        st.subheader(
            "Statement Control"
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

            control = statement_info[
                "control"
            ]

            ending_balance = (
                statement_info[
                    "ending_balance"
                ]
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

            if ending_balance is not None:

                if ending_balance < 0:

                    st.write(
                        "Ending Balance: "
                        f"${abs(ending_balance):,.2f} OD"
                    )

                else:

                    st.write(
                        "Ending Balance: "
                        f"${ending_balance:,.2f}"
                    )

            if (
                control["debit_total"]
                is not None
                and
                control["credit_total"]
                is not None
            ):

                st.divider()

                st.write(
                    f"TD Statement Debits: "
                    f"{control['debit_count']} transactions, "
                    f"${control['debit_total']:,.2f}"
                )

                st.write(
                    f"TD Statement Credits: "
                    f"{control['credit_count']} transactions, "
                    f"${control['credit_total']:,.2f}"
                )

                reconciled = (
                    debit_count
                    == control["debit_count"]
                    and
                    credit_count
                    == control["credit_count"]
                    and
                    abs(
                        debit_total
                        - control["debit_total"]
                    ) < 0.01
                    and
                    abs(
                        credit_total
                        - control["credit_total"]
                    ) < 0.01
                )

                if reconciled:

                    st.success(
                        "✓ STATEMENT RECONCILES"
                    )

                else:

                    st.error(
                        "⚠ STATEMENT DOES NOT RECONCILE"
                    )


        # =================================================
        # CREDIT CARD RECONCILIATION
        # =================================================

        else:

            summary = statement_info[
                "summary"
            ]

            col1, col2, col3 = (
                st.columns(3)
            )

            col1.metric(
                "Transactions",
                transaction_count
            )

            col2.metric(
                "Charges",
                f"${debit_total:,.2f}"
            )

            col3.metric(
                "Payments / Credits",
                f"${credit_total:,.2f}"
            )

            st.write(
                f"Extracted Charges: "
                f"{debit_count} transactions"
            )

            st.write(
                f"Extracted Payments / Credits: "
                f"{credit_count} transactions"
            )

            st.divider()

            if (
                summary["previous_balance"]
                is not None
            ):

                st.write(
                    "TD Previous Balance: "
                    f"${summary['previous_balance']:,.2f}"
                )

            if (
                summary["payments_credits"]
                is not None
            ):

                st.write(
                    "TD Payments & Credits: "
                    f"${summary['payments_credits']:,.2f}"
                )

            if (
                summary["purchases_charges"]
                is not None
            ):

                st.write(
                    "TD Purchases & Other Charges: "
                    f"${summary['purchases_charges']:,.2f}"
                )

            if summary["interest"] is not None:

                st.write(
                    "TD Interest: "
                    f"${summary['interest']:,.2f}"
                )

            if (
                summary["new_balance"]
                is not None
            ):

                st.write(
                    "TD New Balance: "
                    f"${summary['new_balance']:,.2f}"
                )

            # ---------------------------------------------
            # Reconcile using statement equation
            #
            # Previous Balance
            # - Payments/Credits
            # + Charges
            # + Interest
            # = New Balance
            # ---------------------------------------------

            required_summary = [
                summary["previous_balance"],
                summary["payments_credits"],
                summary["purchases_charges"],
                summary["new_balance"]
            ]

            if all(
                value is not None
                for value in required_summary
            ):

                interest = (
                    summary["interest"]
                    if summary["interest"]
                    is not None
                    else 0.0
                )

                calculated_balance = (
                    summary["previous_balance"]
                    -
                    summary["payments_credits"]
                    +
                    summary["purchases_charges"]
                    +
                    interest
                )

                statement_equation_matches = (
                    abs(
                        calculated_balance
                        -
                        summary["new_balance"]
                    )
                    < 0.01
                )

                # Extracted transactions should equal:
                #
                # payments/credits
                # and
                # purchases + interest

                expected_charges = (
                    summary["purchases_charges"]
                    +
                    interest
                )

                extracted_charges_match = (
                    abs(
                        debit_total
                        -
                        expected_charges
                    )
                    < 0.01
                )

                extracted_credits_match = (
                    abs(
                        credit_total
                        -
                        summary[
                            "payments_credits"
                        ]
                    )
                    < 0.01
                )

                reconciled = (
                    statement_equation_matches
                    and
                    extracted_charges_match
                    and
                    extracted_credits_match
                )

                if reconciled:

                    st.success(
                        "✓ CREDIT CARD STATEMENT RECONCILES"
                    )

                else:

                    st.error(
                        "⚠ CREDIT CARD STATEMENT "
                        "DOES NOT RECONCILE"
                    )

                    st.write(
                        "Extracted charges difference: "
                        f"${debit_total - expected_charges:,.2f}"
                    )

                    st.write(
                        "Extracted payments/credits difference: "
                        f"${credit_total - summary['payments_credits']:,.2f}"
                    )

            else:

                st.warning(
                    "Unable to read all credit-card "
                    "statement control totals."
                )


        # =================================================
        # DOWNLOADS
        # =================================================

        st.divider()

        st.subheader(
            "QuickBooks Downloads"
        )

        if reconciled:

            st.success(
                "Statement verified. "
                "Choose your QuickBooks format."
            )

            statement_type = (
                statement_info[
                    "statement_type"
                ]
            )

            csv_data = (
                generate_qbo_online_csv(
                    edited_df,
                    statement_type
                )
            )

            if (
                statement_type
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
                        ][
                            "new_balance"
                        ]
                    )
                )

            col1, col2 = st.columns(2)

            with col1:

                st.write(
                    "QuickBooks Online"
                )

                st.download_button(
                    label=(
                        "Download QuickBooks Online CSV"
                    ),
                    data=csv_data,
                    file_name=(
                        "quickbooks_online.csv"
                    ),
                    mime="text/csv",
                    use_container_width=True
                )

            with col2:

                st.write(
                    "QuickBooks Desktop"
                )

                st.download_button(
                    label=(
                        "Download QuickBooks Desktop QBO"
                    ),
                    data=qbo_data,
                    file_name=(
                        "quickbooks_desktop.qbo"
                    ),
                    mime="application/x-ofx",
                    use_container_width=True
                )

        else:

            st.warning(
                "Downloads are disabled because "
                "the statement does not reconcile."
            )


# =========================================================
# FOOTER
# =========================================================

st.divider()

st.caption(
    "Tax Square Professional Corporation"
)
