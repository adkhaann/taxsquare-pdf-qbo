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
    "Convert bank PDF statements into QuickBooks Online CSV "
    "or QuickBooks Desktop QBO files."
)

st.divider()


# =========================================================
# GENERAL HELPER FUNCTIONS
# =========================================================

def money_to_float(value):

    if value is None:
        return 0.0

    value = (
        str(value)
        .replace(",", "")
        .replace("$", "")
        .strip()
    )

    try:
        return float(value)
    except:
        return 0.0


def parse_td_date(date_text, statement_year):

    date_text = date_text.strip().upper()

    try:

        parsed = datetime.strptime(
            f"{date_text}{statement_year}",
            "%b%d%Y"
        )

        return parsed.strftime("%Y-%m-%d")

    except:
        return date_text


def get_statement_year(text):

    match = re.search(
        r"(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)"
        r"\s+\d{1,2}/(\d{2})",
        text,
        re.IGNORECASE
    )

    if match:
        return 2000 + int(match.group(1))

    return datetime.now().year


def get_statement_control_totals(text):

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


# =========================================================
# TD TRANSACTION EXTRACTION
# =========================================================

def extract_td_transactions(pdf_bytes):

    doc = fitz.open(
        stream=pdf_bytes,
        filetype="pdf"
    )

    transactions = []

    full_text = ""

    # -----------------------------------------------------
    # Collect all PDF text
    # -----------------------------------------------------

    for page in doc:

        full_text += (
            page.get_text("text") + "\n"
        )

    statement_year = get_statement_year(
        full_text
    )

    control = get_statement_control_totals(
        full_text
    )

    # -----------------------------------------------------
    # Process each page
    # -----------------------------------------------------

    for page in doc:

        words = page.get_text("words")

        if not words:
            continue

        page_width = page.rect.width

        # -------------------------------------------------
        # TD statement columns
        # -------------------------------------------------

        debit_left = page_width * 0.31
        debit_right = page_width * 0.47

        credit_left = page_width * 0.47
        credit_right = page_width * 0.63

        description_right = debit_left

        # -------------------------------------------------
        # Find transaction date words
        # -------------------------------------------------

        date_words = []

        for word in words:

            x0, y0, x1, y1, text, block, line, word_no = word

            cleaned = text.strip().upper()

            if re.fullmatch(
                r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2}",
                cleaned
            ):

                date_words.append(word)

        # -------------------------------------------------
        # Process transaction rows
        # -------------------------------------------------

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

                if (
                    abs(
                        center_y -
                        date_center_y
                    )
                    <= tolerance
                ):

                    row_words.append(word)

            if not row_words:
                continue

            row_words.sort(
                key=lambda w: w[0]
            )

            # -------------------------------------------------
            # Description
            # -------------------------------------------------

            description_parts = []

            for word in row_words:

                x0, y0, x1, y1, text, *_ = word

                if x0 < description_right:

                    description_parts.append(
                        text
                    )

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

            # -------------------------------------------------
            # Debit and credit
            # -------------------------------------------------

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

            if (
                debit == 0
                and credit == 0
            ):
                continue

            formatted_date = parse_td_date(
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

    return df, control


# =========================================================
# QUICKBOOKS ONLINE CSV
# =========================================================

def generate_qbo_online_csv(df):

    export_df = df.copy()

    # Credit = money into bank = positive
    # Debit = money out of bank = negative

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
# QUICKBOOKS DESKTOP HELPERS
# =========================================================

def clean_qbo_text(text):

    text = str(text)

    text = text.replace(
        "&",
        "and"
    )

    text = text.replace(
        "<",
        ""
    )

    text = text.replace(
        ">",
        ""
    )

    return text.strip()[:255]


def create_fitid(
    date_text,
    description,
    amount,
    occurrence
):

    """
    Creates a stable unique transaction ID.

    If the same PDF is converted again, the same transaction
    should receive the same FITID.
    """

    source = (
        f"TD|"
        f"{date_text}|"
        f"{description}|"
        f"{amount:.2f}|"
        f"{occurrence}"
    )

    digest = hashlib.sha256(
        source.encode("utf-8")
    ).hexdigest()

    # Numeric-looking ID is closer to TD's own QBO format

    numeric_fitid = str(
        int(
            digest[:15],
            16
        )
    )

    return numeric_fitid[:20]


def td_qbo_datetime(date_object):

    """
    Match TD Web Connect style:
    YYYYMMDD020000[-5:EST]
    """

    return (
        date_object.strftime("%Y%m%d")
        +
        "020000[-5:EST]"
    )


# =========================================================
# QUICKBOOKS DESKTOP QBO GENERATOR
# =========================================================

def generate_desktop_qbo(
    df,
    account_id="5263645"
):

    if df.empty:
        return ""

    working_df = df.copy()

    working_df["DateObject"] = pd.to_datetime(
        working_df["Date"]
    )

    # -----------------------------------------------------
    # Statement dates
    # -----------------------------------------------------

    first_date = (
        working_df["DateObject"]
        .min()
    )

    last_date = (
        working_df["DateObject"]
        .max()
    )

    start_date = (
        first_date.strftime(
            "%Y%m%d"
        )
    )

    end_date = td_qbo_datetime(
        last_date
    )

    server_time = (
        datetime.now()
        .strftime("%Y%m%d%H%M%S")
        +
        "[-5:EST]"
    )

    transaction_blocks = []

    # Used to distinguish identical transactions
    duplicate_counter = {}

    # -----------------------------------------------------
    # Transactions
    # -----------------------------------------------------

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

        transaction_date_object = (
            row["DateObject"]
        )

        transaction_date = (
            transaction_date_object
            .strftime("%Y%m%d")
        )

        posted_date = td_qbo_datetime(
            transaction_date_object
        )

        description = clean_qbo_text(
            row["Description"]
        )

        if amount < 0:

            transaction_type = (
                "DEBIT"
            )

        else:

            transaction_type = (
                "CREDIT"
            )

        # ---------------------------------------------
        # Stable duplicate handling
        # ---------------------------------------------

        duplicate_key = (
            transaction_date,
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
            +
            1
        )

        occurrence = duplicate_counter[
            duplicate_key
        ]

        fitid = create_fitid(
            transaction_date,
            description,
            amount,
            occurrence
        )

        block = (
            "<STMTTRN>\n"
            f"<TRNTYPE>{transaction_type}\n"
            f"<DTPOSTED>{posted_date}\n"
            f"<TRNAMT>{amount:.2f}\n"
            f"<FITID>{fitid}\n"
            f"<NAME>{description}\n"
            "</STMTTRN>"
        )

        transaction_blocks.append(
            block
        )

    transactions_text = "\n".join(
        transaction_blocks
    )

    # -----------------------------------------------------
    # Transaction request UID
    # -----------------------------------------------------

    trnuid_source = (
        f"{account_id}|"
        f"{start_date}|"
        f"{end_date}"
    )

    trnuid_hash = hashlib.sha256(
        trnuid_source.encode("utf-8")
    ).hexdigest()[:12]

    trnuid = (
        f"TAXSQUARE-{trnuid_hash}"
    )

    # -----------------------------------------------------
    # TD-specific Web Connect structure
    #
    # Based on actual TD-generated QBO file:
    #
    # SECURITY:TYPE1
    # INTU.BID: 00002
    # BANKID: 300000100
    # CAD
    # CHECKING
    # -----------------------------------------------------

    qbo_text = f"""OFXHEADER:100
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
</STMTRS>
</STMTTRNRS>
</BANKMSGSRSV1>
</OFX>
"""

    return qbo_text


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

    else:

        if st.button(
            "Process Statement",
            type="primary"
        ):

            pdf_bytes = (
                uploaded_file.getvalue()
            )

            try:

                df, control = (
                    extract_td_transactions(
                        pdf_bytes
                    )
                )

                st.session_state[
                    "transactions"
                ] = df

                st.session_state[
                    "control"
                ] = control

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

    control = st.session_state[
        "control"
    ]

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

        # -------------------------------------------------
        # Totals
        # -------------------------------------------------

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

        # -------------------------------------------------
        # Statement Control
        # -------------------------------------------------

        st.divider()

        st.subheader(
            "Statement Control"
        )

        col1, col2, col3 = st.columns(3)

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

        # -------------------------------------------------
        # Compare with statement totals
        # -------------------------------------------------

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

            debit_difference = (
                debit_total
                -
                control["debit_total"]
            )

            credit_difference = (
                credit_total
                -
                control["credit_total"]
            )

            debit_count_match = (
                debit_count
                ==
                control["debit_count"]
            )

            credit_count_match = (
                credit_count
                ==
                control["credit_count"]
            )

            debit_total_match = (
                abs(
                    debit_difference
                ) < 0.01
            )

            credit_total_match = (
                abs(
                    credit_difference
                ) < 0.01
            )

            reconciled = (
                debit_count_match
                and
                credit_count_match
                and
                debit_total_match
                and
                credit_total_match
            )

            if reconciled:

                st.success(
                    "✓ STATEMENT RECONCILES"
                )

            else:

                st.error(
                    "⚠ STATEMENT DOES NOT RECONCILE"
                )

                st.write(
                    f"Debit difference: "
                    f"${debit_difference:,.2f}"
                )

                st.write(
                    f"Credit difference: "
                    f"${credit_difference:,.2f}"
                )

                if not debit_count_match:

                    st.write(
                        "Debit transaction count difference: "
                        f"{debit_count - control['debit_count']}"
                    )

                if not credit_count_match:

                    st.write(
                        "Credit transaction count difference: "
                        f"{credit_count - control['credit_count']}"
                    )


        # =================================================
        # DOWNLOAD SECTION
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

            # ---------------------------------------------
            # QBO Online CSV
            # ---------------------------------------------

            csv_data = (
                generate_qbo_online_csv(
                    edited_df
                )
            )

            # ---------------------------------------------
            # QuickBooks Desktop QBO
            # ---------------------------------------------

            qbo_data = (
                generate_desktop_qbo(
                    edited_df,
                    account_id="5263645"
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
