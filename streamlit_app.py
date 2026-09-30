import streamlit as st
import pandas as pd
import fitz
import re
from datetime import datetime


# ---------------------------------------------------------
# PAGE SETTINGS
# ---------------------------------------------------------

st.set_page_config(
    page_title="Tax Square PDF to QuickBooks Converter",
    page_icon="📄",
    layout="wide"
)

st.title("PDF to QuickBooks Converter")
st.write("Convert TD bank PDF statements into QuickBooks-ready files.")

st.divider()


# ---------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------

def money_to_float(value):
    """
    Convert values such as:
    1,500.00
    $1,500.00
    into float.
    """
    if value is None:
        return 0.0

    value = str(value).replace(",", "").replace("$", "").strip()

    try:
        return float(value)
    except:
        return 0.0


def parse_td_date(date_text, statement_year):
    """
    Convert TD dates such as MAY01 into 2026-05-01.
    """

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
    """
    Find the statement year from text such as:
    APR 30/26 - MAY 29/26
    """

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
    """
    Read TD's printed control totals:
    Credits 7 7,071.00
    Debits 13 10,405.55
    """

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
        credit_count = int(credit_match.group(1))
        credit_total = money_to_float(credit_match.group(2))

    if debit_match:
        debit_count = int(debit_match.group(1))
        debit_total = money_to_float(debit_match.group(2))

    return {
        "credit_count": credit_count,
        "credit_total": credit_total,
        "debit_count": debit_count,
        "debit_total": debit_total
    }


# ---------------------------------------------------------
# TD TRANSACTION EXTRACTION
# ---------------------------------------------------------

def extract_td_transactions(pdf_bytes):

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    transactions = []

    full_text = ""

    # -----------------------------------------------------
    # First collect text from entire PDF
    # -----------------------------------------------------

    for page in doc:
        full_text += page.get_text("text") + "\n"

    statement_year = get_statement_year(full_text)

    control = get_statement_control_totals(full_text)

    # -----------------------------------------------------
    # Process each page
    # -----------------------------------------------------

    for page in doc:

        words = page.get_text("words")

        if not words:
            continue

        # -------------------------------------------------
        # Determine page width
        # -------------------------------------------------

        page_width = page.rect.width

        # The uploaded TD statement uses these columns:
        #
        # DESCRIPTION
        # CHEQUE/DEBIT
        # DEPOSIT/CREDIT
        # DATE
        # BALANCE
        #
        # We use relative page positions so the parser
        # remains usable if PDF scaling changes slightly.
        # -------------------------------------------------

        debit_left = page_width * 0.31
        debit_right = page_width * 0.47

        credit_left = page_width * 0.47
        credit_right = page_width * 0.63

        date_left = page_width * 0.63
        date_right = page_width * 0.73

        description_right = debit_left

        # -------------------------------------------------
        # Find all date words
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
        # Process each transaction row
        # -------------------------------------------------

        for date_word in date_words:

            dx0, dy0, dx1, dy1, date_text, _, _, _ = date_word

            # Skip balance-forward row
            row_words = []

            # TD rows are close vertically.
            tolerance = 3.5

            for word in words:

                x0, y0, x1, y1, text, block, line, word_no = word

                center_y = (y0 + y1) / 2
                date_center_y = (dy0 + dy1) / 2

                if abs(center_y - date_center_y) <= tolerance:
                    row_words.append(word)

            if not row_words:
                continue

            # -------------------------------------------------
            # Sort row left to right
            # -------------------------------------------------

            row_words.sort(key=lambda w: w[0])

            # -------------------------------------------------
            # Description
            # -------------------------------------------------

            description_parts = []

            for word in row_words:

                x0, y0, x1, y1, text, *_ = word

                if x0 < description_right:
                    description_parts.append(text)

            description = " ".join(description_parts).strip()

            # Remove date accidentally included in description
            description = description.replace(date_text, "").strip()

            # Skip non-transaction rows
            upper_description = description.upper()

            if "BALANCE FORWARD" in upper_description:
                continue

            if "NEXT STATEMENT" in upper_description:
                continue

            if "MONTHLY AVER" in upper_description:
                continue

            if "MONTHLY MIN" in upper_description:
                continue

            if "DEP CONTENT" in upper_description:
                continue

            if "BUSINESS LINE OF CREDIT LIMIT" in upper_description:
                continue

            if description == "":
                continue

            # -------------------------------------------------
            # Find money values by physical column
            # -------------------------------------------------

            debit = 0.0
            credit = 0.0

            for word in row_words:

                x0, y0, x1, y1, text, *_ = word

                cleaned = text.replace(",", "").replace("$", "").strip()

                if not re.fullmatch(r"\d+\.\d{2}", cleaned):
                    continue

                amount = money_to_float(cleaned)

                # Use CENTER of word for more reliable placement
                center_x = (x0 + x1) / 2

                if debit_left <= center_x < debit_right:
                    debit = amount

                elif credit_left <= center_x < credit_right:
                    credit = amount

            # -------------------------------------------------
            # Ignore rows with no debit or credit amount
            # -------------------------------------------------

            if debit == 0 and credit == 0:
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

    # -----------------------------------------------------
    # DataFrame
    # -----------------------------------------------------

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

        # Remove exact duplicate rows
        df = df.drop_duplicates().reset_index(drop=True)

    return df, control


# ---------------------------------------------------------
# USER CONTROLS
# ---------------------------------------------------------

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


# ---------------------------------------------------------
# FILE UPLOAD
# ---------------------------------------------------------

uploaded_file = st.file_uploader(
    "Upload TD PDF Bank Statement",
    type=["pdf"]
)


if uploaded_file is not None:

    st.success(
        f"Uploaded: {uploaded_file.name}"
    )

    if bank != "TD Canada Trust":

        st.warning(
            "Please select TD Canada Trust before processing."
        )

    else:

        if st.button(
            "Process Statement",
            type="primary"
        ):

            pdf_bytes = uploaded_file.getvalue()

            try:

                df, control = extract_td_transactions(
                    pdf_bytes
                )

                st.session_state["transactions"] = df
                st.session_state["control"] = control

            except Exception as e:

                st.error(
                    f"Unable to process statement: {e}"
                )


# ---------------------------------------------------------
# RESULTS
# ---------------------------------------------------------

if "transactions" in st.session_state:

    df = st.session_state["transactions"]
    control = st.session_state["control"]

    st.divider()

    st.subheader("Transaction Review")

    if df.empty:

        st.error(
            "No transactions were detected."
        )

    else:

        # -------------------------------------------------
        # Editable transaction table
        # -------------------------------------------------

        edited_df = st.data_editor(
            df,
            use_container_width=True,
            hide_index=True,
            num_rows="dynamic",
            column_config={
                "Date": st.column_config.TextColumn(
                    "Date"
                ),
                "Description": st.column_config.TextColumn(
                    "Description"
                ),
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

        # -------------------------------------------------
        # Calculate totals
        # -------------------------------------------------

        debit_total = edited_df["Debit"].sum()
        credit_total = edited_df["Credit"].sum()

        debit_count = int(
            (edited_df["Debit"] > 0).sum()
        )

        credit_count = int(
            (edited_df["Credit"] > 0).sum()
        )

        transaction_count = len(edited_df)

        # -------------------------------------------------
        # Statement Control
        # -------------------------------------------------

        st.divider()

        st.subheader("Statement Control")

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
            f"Extracted Debits: {debit_count} transactions"
        )

        st.write(
            f"Extracted Credits: {credit_count} transactions"
        )

        # -------------------------------------------------
        # TD CONTROL TOTALS
        # -------------------------------------------------

        if (
            control["debit_total"] is not None
            and control["credit_total"] is not None
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
                debit_total -
                control["debit_total"]
            )

            credit_difference = (
                credit_total -
                control["credit_total"]
            )

            debit_count_match = (
                debit_count ==
                control["debit_count"]
            )

            credit_count_match = (
                credit_count ==
                control["credit_count"]
            )

            debit_total_match = (
                abs(debit_difference) < 0.01
            )

            credit_total_match = (
                abs(credit_difference) < 0.01
            )

            reconciled = (
                debit_count_match
                and credit_count_match
                and debit_total_match
                and credit_total_match
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

        # -------------------------------------------------
        # QUICKBOOKS CSV
        # -------------------------------------------------

        st.divider()

        quickbooks_df = edited_df.copy()

        # QuickBooks-friendly Amount column:
        # Money IN = positive
        # Money OUT = negative

        quickbooks_df["Amount"] = (
            quickbooks_df["Credit"]
            -
            quickbooks_df["Debit"]
        )

        quickbooks_export = quickbooks_df[
            [
                "Date",
                "Description",
                "Amount"
            ]
        ].copy()

        csv = quickbooks_export.to_csv(
            index=False
        )

        st.download_button(
            label="Download QuickBooks CSV",
            data=csv,
            file_name="quickbooks_transactions.csv",
            mime="text/csv"
        )


# ---------------------------------------------------------
# FOOTER
# ---------------------------------------------------------

st.divider()

st.caption(
    "Tax Square Professional Corporation"
)
