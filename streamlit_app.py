import streamlit as st
import pandas as pd
import fitz
import re
from datetime import datetime
from io import BytesIO


# =========================================================
# PAGE SETUP
# =========================================================

st.set_page_config(
    page_title="Tax Square PDF to QuickBooks Converter",
    page_icon="📄",
    layout="wide"
)

st.title("PDF to QuickBooks Converter")
st.write(
    "Convert TD bank and credit card PDF statements "
    "into QuickBooks-ready CSV and QBO files."
)

st.divider()


# =========================================================
# GENERAL HELPERS
# =========================================================

def clean_amount(value):

    if value is None:
        return 0.0

    value = str(value)

    value = (
        value
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


def money_to_float(value):
    return clean_amount(value)


def extract_statement_year(text):

    # First try normal statement date

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

    # TD chequing statement format

    match = re.search(
        r"([A-Z]{3})\s*(\d{1,2})/(\d{2})\s*-\s*"
        r"([A-Z]{3})\s*(\d{1,2})/(\d{2})",
        text,
        re.IGNORECASE
    )

    if match:
        return 2000 + int(match.group(6))

    return datetime.now().year


# =========================================================
# TD CHEQUING CONTROL TOTALS
# =========================================================

def get_td_chequing_control_totals(text):

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


# =========================================================
# TD CHEQUING PARSER
# =========================================================

def extract_td_chequing_transactions(pdf_bytes):

    doc = fitz.open(
        stream=pdf_bytes,
        filetype="pdf"
    )

    full_text = ""

    for page in doc:
        full_text += page.get_text("text") + "\n"

    statement_year = extract_statement_year(
        full_text
    )

    controls = get_td_chequing_control_totals(
        full_text
    )

    transactions = []

    valid_months = {
        "JAN", "FEB", "MAR", "APR",
        "MAY", "JUN", "JUL", "AUG",
        "SEP", "OCT", "NOV", "DEC"
    }

    for page in doc:

        words = page.get_text("words")

        rows = {}

        for word in words:

            x0, y0, x1, y1, text = word[:5]

            row_key = round(y0 / 3) * 3

            if row_key not in rows:
                rows[row_key] = []

            rows[row_key].append({
                "x": x0,
                "text": text
            })

        for y in sorted(rows.keys()):

            row_words = sorted(
                rows[y],
                key=lambda item: item["x"]
            )

            row_text = " ".join(
                item["text"]
                for item in row_words
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

            if "BALANCE FORWARD" in row_text.upper():
                continue

            month = date_match.group(1).upper()

            if month not in valid_months:
                continue

            day = int(
                date_match.group(2)
            )

            description_parts = []

            amount_candidates = []

            for item in row_words:

                x = item["x"]
                text = item["text"]

                if re.fullmatch(
                    r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|"
                    r"SEP|OCT|NOV|DEC)\d{2}",
                    text,
                    re.IGNORECASE
                ):
                    continue

                if x < 300:

                    description_parts.append(
                        text
                    )

                if re.fullmatch(
                    r"[\d,]+\.\d{2}",
                    text
                ):

                    amount_candidates.append(
                        (x, text)
                    )

            description = " ".join(
                description_parts
            ).strip()

            if not description:
                continue

            skip_words = [
                "DESCRIPTION",
                "CREDITS",
                "DEBITS",
                "NEXT STATEMENT",
                "MONTHLY AVER",
                "MONTHLY MIN",
                "DEP CONTENT"
            ]

            if any(
                phrase in description.upper()
                for phrase in skip_words
            ):
                continue

            if not amount_candidates:
                continue

            # -------------------------------------------------
            # IMPORTANT:
            # Working TD chequing structure.
            #
            # Credits are farther left.
            # Debits are farther right.
            # Balance column is ignored.
            # -------------------------------------------------

            debit = 0.0
            credit = 0.0

            for x, amount_text in amount_candidates:

                amount = clean_amount(
                    amount_text
                )

                # Credit / deposit column

                if 300 <= x < 390:

                    credit = amount

                # Debit / withdrawal column

                elif 390 <= x < 500:

                    debit = amount

            if debit == 0 and credit == 0:
                continue

            try:

                transaction_date = (
                    datetime.strptime(
                        f"{month} {day:02d} {statement_year}",
                        "%b %d %Y"
                    )
                    .strftime("%Y-%m-%d")
                )

            except:

                transaction_date = (
                    f"{month} {day:02d} {statement_year}"
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

        df = (
            df
            .drop_duplicates()
            .reset_index(drop=True)
        )

    return df, controls


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

    statement_year = extract_statement_year(
        full_text
    )

    # =====================================================
    # CREDIT CARD STATEMENT SUMMARY
    # =====================================================

    summary = {
        "previous_balance": None,
        "payments_credits": None,
        "purchases_charges": None,
        "cash_advances": None,
        "interest": None,
        "fees": None,
        "new_balance": None
    }

    patterns = {

        "previous_balance":
            r"Previous Balance\s+\$([\d,]+\.\d{2})",

        "payments_credits":
            r"Payments\s*&\s*Credits\s+\$([\d,]+\.\d{2})",

        "purchases_charges":
            r"Purchases\s*&\s*Other Charges\s+\$([\d,]+\.\d{2})",

        "cash_advances":
            r"Cash Advances\s+\$([\d,]+\.\d{2})",

        "interest":
            r"Interest\s+\$([\d,]+\.\d{2})",

        "fees":
            r"Fees\s+\$([\d,]+\.\d{2})",

        "new_balance":
            r"NEW BALANCE\s+\$([\d,]+\.\d{2})"
    }

    for key, pattern in patterns.items():

        match = re.search(
            pattern,
            full_text,
            re.IGNORECASE
        )

        if match:

            summary[key] = clean_amount(
                match.group(1)
            )

    # =====================================================
    # ACCOUNT NUMBER
    # =====================================================

    account_match = re.search(
        r"Account Number:\s*"
        r"(?:\d{4}\s+)?"
        r"(?:\d{2}XX\s+XXXX\s+)?"
        r"(\d{4})",
        full_text,
        re.IGNORECASE
    )

    if account_match:
        account_id = account_match.group(1)
    else:
        account_id = "0000"

    # =====================================================
    # TRANSACTIONS
    # =====================================================

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

            # TD transaction-date month position

            if not (40 <= x0 <= 60):
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

                # TD's description baseline is slightly
                # different from the transaction dates.

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

            # =================================================
            # DAY
            # =================================================

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

            # =================================================
            # AMOUNT
            # =================================================

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

            # =================================================
            # DESCRIPTION
            # =================================================

            description_parts = []

            for word in row_words:

                wx0, wy0, wx1, wy1, text = (
                    word[:5]
                )

                if 130 <= wx0 < 295:

                    description_parts.append(
                        text.strip()
                    )

            description = " ".join(
                description_parts
            ).strip()

            if not description:
                continue

            # =================================================
            # DEBIT / CREDIT
            # =================================================

            numeric_amount = clean_amount(
                amount_text
            )

            debit = 0.0
            credit = 0.0

            # For a credit card:
            #
            # Positive amount = purchase / charge
            # Negative amount = payment / credit

            if numeric_amount < 0:

                credit = abs(
                    numeric_amount
                )

            else:

                debit = numeric_amount

            # =================================================
            # DATE
            # =================================================

            try:

                transaction_date = (
                    datetime.strptime(
                        f"{month_text} {day} {statement_year}",
                        "%b %d %Y"
                    )
                    .strftime("%Y-%m-%d")
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
        "summary": summary,
        "account_id": account_id
    }

    return df, statement_info


# =========================================================
# QUICKBOOKS CSV
# =========================================================

def create_quickbooks_csv(df):

    export_df = pd.DataFrame()

    export_df["Date"] = pd.to_datetime(
        df["Date"]
    ).dt.strftime("%d/%m/%Y")

    export_df["Description"] = df[
        "Description"
    ]

    # Bank / credit card convention:
    #
    # Debit = money leaving bank or charge on card
    # Credit = money entering bank or payment to card

    export_df["Amount"] = (
        df["Credit"]
        -
        df["Debit"]
    )

    return export_df.to_csv(
        index=False
    ).encode("utf-8")


# =========================================================
# QBO / WEB CONNECT FILE
# =========================================================

def create_qbo_file(
    df,
    account_type,
    account_id="0000"
):

    # QuickBooks OFX/QBO format

    now = datetime.now().strftime(
        "%Y%m%d%H%M%S"
    )

    if account_type == "Credit Card":

        acct_type_tag = ""

        account_section = f"""
<CREDITCARDMSGSRSV1>
<CCSTMTTRNRS>
<TRNUID>1
<STATUS>
<CODE>0
<SEVERITY>INFO
</STATUS>
<CCSTMTRS>
<CURDEF>CAD
<CCACCTFROM>
<ACCTID>{account_id}
</CCACCTFROM>
"""

        closing_section = """
</CCSTMTRS>
</CCSTMTTRNRS>
</CREDITCARDMSGSRSV1>
"""

    else:

        account_section = f"""
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
"""

        closing_section = """
</STMTRS>
</STMTTRNRS>
</BANKMSGSRSV1>
"""

    qbo = """OFXHEADER:100
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
<DTSERVER>""" + now + """
<LANGUAGE>ENG
<FI>
<ORG>TD Canada Trust
<FID>004
</FI>
</SONRS>
</SIGNONMSGSRSV1>
"""

    qbo += account_section

    qbo += """
<BANKTRANLIST>
"""

    if not df.empty:

        start_date = (
            pd.to_datetime(
                df["Date"]
            )
            .min()
            .strftime("%Y%m%d")
        )

        end_date = (
            pd.to_datetime(
                df["Date"]
            )
            .max()
            .strftime("%Y%m%d")
        )

    else:

        start_date = now[:8]
        end_date = now[:8]

    qbo += (
        f"<DTSTART>{start_date}\n"
        f"<DTEND>{end_date}\n"
    )

    for index, row in df.iterrows():

        date_value = (
            pd.to_datetime(
                row["Date"]
            )
            .strftime("%Y%m%d")
        )

        debit = float(
            row["Debit"]
        )

        credit = float(
            row["Credit"]
        )

        # QuickBooks:
        # money out / card purchase = negative
        # money in / card payment = positive

        amount = credit - debit

        if amount < 0:

            if account_type == "Credit Card":
                trn_type = "DEBIT"
            else:
                trn_type = "DEBIT"

        else:

            if account_type == "Credit Card":
                trn_type = "CREDIT"
            else:
                trn_type = "CREDIT"

        description = str(
            row["Description"]
        )

        # Avoid OFX-breaking characters

        description = (
            description
            .replace("&", "and")
            .replace("<", "")
            .replace(">", "")
        )

        fitid = (
            f"{date_value}"
            f"{index + 1:05d}"
            f"{abs(int(round(amount * 100)))}"
        )

        qbo += f"""
<STMTTRN>
<TRNTYPE>{trn_type}
<DTPOSTED>{date_value}
<TRNAMT>{amount:.2f}
<FITID>{fitid}
<NAME>{description[:32]}
<MEMO>{description[:255]}
</STMTTRN>
"""

    qbo += """
</BANKTRANLIST>
"""

    # Required balance block

    qbo += f"""
<LEDGERBAL>
<BALAMT>0.00
<DTASOF>{end_date}
</LEDGERBAL>
"""

    qbo += closing_section

    qbo += """
</OFX>
"""

    return qbo.encode(
        "cp1252",
        errors="replace"
    )


# =========================================================
# USER INTERFACE
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
            "Chequing",
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


process_button = st.button(
    "Process Statement",
    type="primary"
)


# =========================================================
# PROCESS
# =========================================================

if (
    process_button
    and
    uploaded_file is not None
):

    pdf_bytes = uploaded_file.getvalue()

    try:

        # =================================================
        # CHEQUING
        # =================================================

        if account_type == "Chequing":

            df, controls = (
                extract_td_chequing_transactions(
                    pdf_bytes
                )
            )

            statement_info = {
                "account_id": "0000"
            }

        # =================================================
        # CREDIT CARD
        # =================================================

        else:

            df, statement_info = (
                extract_td_credit_card_transactions(
                    pdf_bytes
                )
            )

            controls = None

        # =================================================
        # STORE RESULTS
        # =================================================

        st.session_state["transactions"] = df
        st.session_state["controls"] = controls
        st.session_state[
            "statement_info"
        ] = statement_info

        st.session_state[
            "processed_account_type"
        ] = account_type

    except Exception as e:

        st.error(
            f"Error processing statement: {e}"
        )


# =========================================================
# RESULTS
# =========================================================

if "transactions" in st.session_state:

    df = st.session_state[
        "transactions"
    ]

    processed_account_type = (
        st.session_state.get(
            "processed_account_type",
            account_type
        )
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

        # =================================================
        # DISPLAY TABLE
        # =================================================

        display_df = df.copy()

        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Debit": st.column_config.NumberColumn(
                    "Debit",
                    format="$%.2f"
                ),
                "Credit": st.column_config.NumberColumn(
                    "Credit",
                    format="$%.2f"
                )
            }
        )

        st.divider()

        st.header(
            "Statement Control"
        )

        transaction_count = len(
            df
        )

        total_debits = round(
            df["Debit"].sum(),
            2
        )

        total_credits = round(
            df["Credit"].sum(),
            2
        )

        debit_count = int(
            (df["Debit"] > 0).sum()
        )

        credit_count = int(
            (df["Credit"] > 0).sum()
        )

        metric1, metric2, metric3 = (
            st.columns(3)
        )

        metric1.metric(
            "Transactions",
            transaction_count
        )

        metric2.metric(
            "Total Debits",
            f"${total_debits:,.2f}"
        )

        metric3.metric(
            "Total Credits",
            f"${total_credits:,.2f}"
        )

        st.write(
            f"Extracted Debits: "
            f"{debit_count} transactions"
        )

        st.write(
            f"Extracted Credits: "
            f"{credit_count} transactions"
        )

        st.divider()

        # =================================================
        # CHEQUING RECONCILIATION
        # =================================================

        if processed_account_type == "Chequing":

            controls = st.session_state.get(
                "controls"
            )

            if controls:

                td_debit_count = controls.get(
                    "debit_count"
                )

                td_debit_total = controls.get(
                    "debit_total"
                )

                td_credit_count = controls.get(
                    "credit_count"
                )

                td_credit_total = controls.get(
                    "credit_total"
                )

                if (
                    td_debit_count is not None
                    and
                    td_debit_total is not None
                ):

                    st.write(
                        f"TD Statement Debits: "
                        f"{td_debit_count} transactions, "
                        f"${td_debit_total:,.2f}"
                    )

                if (
                    td_credit_count is not None
                    and
                    td_credit_total is not None
                ):

                    st.write(
                        f"TD Statement Credits: "
                        f"{td_credit_count} transactions, "
                        f"${td_credit_total:,.2f}"
                    )

                debit_ok = (
                    td_debit_count == debit_count
                    and
                    abs(
                        td_debit_total
                        -
                        total_debits
                    ) < 0.01
                )

                credit_ok = (
                    td_credit_count == credit_count
                    and
                    abs(
                        td_credit_total
                        -
                        total_credits
                    ) < 0.01
                )

                if debit_ok and credit_ok:

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

            statement_info = (
                st.session_state.get(
                    "statement_info",
                    {}
                )
            )

            summary = statement_info.get(
                "summary",
                {}
            )

            purchases = summary.get(
                "purchases_charges"
            )

            interest = summary.get(
                "interest"
            )

            fees = summary.get(
                "fees"
            )

            payments = summary.get(
                "payments_credits"
            )

            new_balance = summary.get(
                "new_balance"
            )

            if purchases is not None:

                st.write(
                    "TD Purchases & Other Charges: "
                    f"${purchases:,.2f}"
                )

            if interest is not None:

                st.write(
                    "TD Interest: "
                    f"${interest:,.2f}"
                )

            if fees is not None:

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
                (purchases or 0)
                +
                (interest or 0)
                +
                (fees or 0)
            )

            charges_ok = (
                abs(
                    expected_charges
                    -
                    total_debits
                )
                < 0.01
            )

            payments_ok = (
                payments is not None
                and
                abs(
                    payments
                    -
                    total_credits
                )
                < 0.01
            )

            if charges_ok and payments_ok:

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
                    f"${total_debits:,.2f}"
                )

                if payments is not None:

                    st.write(
                        "Expected Payments/Credits: "
                        f"${payments:,.2f}"
                    )

                    st.write(
                        "Extracted Payments/Credits: "
                        f"${total_credits:,.2f}"
                    )

        # =================================================
        # DOWNLOAD FILES
        # =================================================

        st.divider()

        st.subheader(
            "Download QuickBooks Files"
        )

        csv_file = create_quickbooks_csv(
            df
        )

        statement_info = (
            st.session_state.get(
                "statement_info",
                {}
            )
        )

        account_id = statement_info.get(
            "account_id",
            "0000"
        )

        qbo_file = create_qbo_file(
            df,
            processed_account_type,
            account_id
        )

        download1, download2 = (
            st.columns(2)
        )

        with download1:

            st.download_button(
                label="Download QuickBooks CSV",
                data=csv_file,
                file_name=(
                    "quickbooks_transactions.csv"
                ),
                mime="text/csv"
            )

        with download2:

            st.download_button(
                label="Download QuickBooks QBO",
                data=qbo_file,
                file_name=(
                    "quickbooks_webconnect.qbo"
                ),
                mime="application/octet-stream"
            )


# =========================================================
# FOOTER
# =========================================================

st.divider()

st.caption(
    "Tax Square Professional Corporation"
)
