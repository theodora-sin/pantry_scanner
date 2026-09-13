import sqlite3
import re
import calendar
from datetime import datetime
from pathlib import Path
 
from flask import Flask, request, jsonify, render_template, send_from_directory
from PIL import Image
import pytesseract
from pyzbar.pyzbar import decode as read_barcodes_from_image
import requests
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


app= Flask(__name__)

PHOTO=Path("photos")
PHOTO.mkdir(exist_ok=True)
DATABASE = "pantry.db"

# create a database table if it is not exist
def create_databse():
    connection = sqlite3.connect(DATABASE)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS scanned_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            photo_path TEXT NOT NULL,
            raw_text TEXT,
            expiry_date_as_read TEXT,
            expiry_date_sortable TEXT,
            barcode TEXT,
            product_name TEXT,
            brand TEXT,
            needs_review INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)
    connection.commit()
    connection.close()

# find an expiry date in OCR text
MONTH = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}
def find_expiry_date(ocr_text):
    """
    Looks through OCR text, find something looks like a date.
    Returns two things:
      - the exact text it found (e.g. "25/12/2026")
      - a standardized YYYY-MM-DD version (to sort by)
    If nothing date-like is found at all, returns (None, None).
    """

    # Style 1: eg: 5/2/2020
    match = re.search(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b", ocr_text)
    if match:
        day_text, month_text, year_text = match.group(1), match.group(2), match.group(3)
        found_text = match.group(0)
        try:
            day = int(day_text)
            month = int(month_text)
            year = int(year_text)
            if year < 100:
                year += 2000  # "26" -> 2026
            sortable_date = f"{year:04d}-{month:02d}-{day:02d}"
            return found_text, sortable_date
        except ValueError:
            # The numbers didn't form a real date (like month 13)
            return found_text, None

    #Style 2 eg: 24 Mar 2026
    match = re.search(
        r"\b(\d{1,2})\s*([A-Za-z]{3})[A-Za-z]*\s*(\d{2,4})\b",
        ocr_text,
        re.IGNORECASE,
    )
    if match:
        day_text, month_name, year_text = match.group(1), match.group(2), match.group(3)
        found_text = match.group(0)
        month = MONTH.get(month_name.upper())
        if month is not None:
            try:
                day = int(day_text)
                year = int(year_text)
                if year < 100:
                    year += 2000
                sortable_date = f"{year:04d}-{month:02d}-{day:02d}"
                return found_text, sortable_date
            except ValueError:
                return found_text, None    

    #Style 3 : 2026-3-9
    match = re.search(r"\b(20\d{2})[/\-.](\d{1,2})[/\-.](\d{1,2})\b", ocr_text)
    if match:
        year_text, month_text, day_text = match.group(1), match.group(2), match.group(3)
        found_text = match.group(0)
        try:
            year = int(year_text)
            month = int(month_text)
            day = int(day_text)
            sortable_date = f"{year:04d}-{month:02d}-{day:02d}"
            return found_text, sortable_date
        except ValueError:
            return found_text, None

# 8 digit with no seperation 13072021
    match = re.search(r"\b(\d{2})(\d{2})(\d{4})\b", ocr_text)
    if match:
        day_text, month_text, year_text = match.group(1), match.group(2), match.group(3)
        found_text = match.group(0)
        try:
            day = int(day_text)
            month = int(month_text)
            year = int(year_text)
            sortable_date = f"{year:04d}-{month:02d}-{day:02d}"
            return found_text, sortable_date
        except ValueError:
            return found_text, None
 
    # Nothing matched any of the three styles.
    return None, None    

# use public database to find the produce
def camera_barcode(barcode_number):
    try:
        response = requests.get(
            f"https://world.openfoodfacts.org/api/v2/product/{barcode_number}.json",
            timeout=5,
        )
        data = response.json()
    except requests.RequestException as error:
        print(f"Could not reach Open Food Facts (continuing without it): {error}")
        return None 
 
    product_was_found = data.get("status") == 1
    if not product_was_found:
        return None
 
    product_info = data.get("product", {})
    return {
        "name": product_info.get("product_name"),
        "brand": product_info.get("brands"),
    }

#ESP-32-Cam send photo into here
@app.route("/decode-label", methods=["POST"])
def decode_label():
    photo_bytes = request.get_data()
    if not photo_bytes:
        return jsonify({"error": "No image data received"}), 400
 
    # Save the photo.
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}.jpg"
    path = PHOTO / filename
    path.write_bytes(photo_bytes)
 
    image = Image.open(path)
 
    # Read any text on the label.
    ocr_text = pytesseract.image_to_string(image, config='--psm 6')
    expiry_read, expiry_sortable = find_expiry_date(ocr_text)
 
    # Look for a barcode
    barcodes_found = read_barcodes_from_image(image)
    if barcodes_found:
        barcode_number = barcodes_found[0].data.decode("utf-8")
    else:
        barcode_number = None
 
    if barcode_number:
        product_info = camera_barcode(barcode_number)
    else:
        product_info = None
 
    # flag to show the produce couldn't identify.
    is_missing_something = (expiry_sortable is None) or (product_info is None)
 
    # Save everything to the database.
    connection = sqlite3.connect(DATABASE)
    connection.execute(
        """
        INSERT INTO scanned_items
            (photo_path, raw_text, expiry_date_as_read, expiry_date_sortable,
             barcode, product_name, brand, needs_review, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            filename,
            ocr_text,
            expiry_read,
            expiry_sortable,
            barcode_number,
            product_info["name"] if product_info else None,
            product_info["brand"] if product_info else None,
            int(is_missing_something),
            datetime.now().isoformat(),
        ),
    )
    connection.commit()
    connection.close()
 
    print(
        f"Scanned a photo. Expiry date: {expiry_sortable} "
        f"(as printed: {expiry_read}). Barcode: {barcode_number}. "
        f"Needs review: {is_missing_something}"
    )
 
    return jsonify({
        "success": True,
        "expiry_date": expiry_sortable,
        "barcode": barcode_number,
        "product_name": product_info["name"] if product_info else None,
        "needs_review": is_missing_something,
    })

# sorted the item from soonest 
@app.route("/items")
def get_all_items():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row  
    rows = connection.execute("""
        SELECT * FROM scanned_items
        ORDER BY
            CASE WHEN expiry_date_sortable IS NULL THEN 1 ELSE 0 END,
            expiry_date_sortable ASC
    """).fetchall()
    connection.close()
 
    dictionaries = [dict(row) for row in rows]
    return jsonify(dictionaries)

@app.route("/items/<int:item_id>", methods=["DELETE"])
def delete_item(item_id):
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row

    row = connection.execute(
        "SELECT photo_path FROM scanned_items WHERE id = ?", (item_id,)
    ).fetchone()

    if row is None:
        connection.close()
        return jsonify({"error": "No item with that id"}), 404

    # delete photo row + file
    photo_file = PHOTO / row["photo_path"]
    if photo_file.exists():
        photo_file.unlink()
    connection.execute("DELETE FROM scanned_items WHERE id = ?", (item_id,))
    connection.commit()
    connection.close()
    return jsonify({"success": True})

@app.route("/items/<int:item_id>", methods=["PATCH"])
def update_item(item_id):
    updates = request.get_json()
    if not updates:
        return jsonify({"error": "No update data received"}), 400
 
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
 
    row = connection.execute(
        "SELECT * FROM scanned_items WHERE id = ?", (item_id,)
    ).fetchone()
 
    if row is None:
        connection.close()
        return jsonify({"error": "No item with that id"}), 404
 
    new_product_name = updates.get("product_name", row["product_name"])
    new_expiry_date_sortable = updates.get("expiry_date_sortable", row["expiry_date_sortable"])
    new_expiry_date_as_read = new_expiry_date_sortable  # once typed by hand, both can just match
 
    # If both are now filled in, this item no longer needs review.
    still_needs_review = (new_expiry_date_sortable is None) or (not new_product_name)
 
    connection.execute(
        """
        UPDATE scanned_items
        SET product_name = ?,
            expiry_date_sortable = ?,
            expiry_date_as_read = ?,
            needs_review = ?
        WHERE id = ?
        """,
        (
            new_product_name,
            new_expiry_date_sortable,
            new_expiry_date_as_read,
            int(still_needs_review),
            item_id,
        ),
    )
    connection.commit()
    connection.close()
 
    return jsonify({"success": True})

@app.route("/dashboard")
def dashboard():
    return render_template("index.html")
 
 
@app.route("/photos/<path:filename>")
def serve_photo(filename):
    return send_from_directory(PHOTO, filename)

#start the server
if __name__ == "__main__":
    create_databse()
    app.run(host="0.0.0.0", port=5000)