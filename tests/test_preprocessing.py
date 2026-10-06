from matching.preprocessing import (
    normalize_address, normalize_dob, normalize_email, normalize_name, normalize_phone, normalize_record, soundex, surname,
)


def test_name_lowercase_punctuation_titles_whitespace():
    assert normalize_name("  Mr.  RAHUL   Sharma ") == "rahul sharma"
    assert normalize_name("Dr. Priya-Singh") == "priya singh"
    assert normalize_name("Kumar, Nikhil") == "kumar nikhil"
    assert normalize_name(None) is None
    assert normalize_name("   ") is None


def test_surname_is_last_token():
    assert surname("rahul sharma") == "sharma"
    assert surname("rahul") == "rahul"


def test_email_lowercase_trim_whitespace():
    assert normalize_email("  Rahul.Sharma @Gmail.com ") == "rahul.sharma@gmail.com"
    assert normalize_email("") is None


def test_phone_country_code_and_formats():
    expected = "9876543210"
    for raw in ["9876543210", "+91 9876543210", "+91-9876543210", "09876543210", "91 98765 43210", "(+91) 98765-43210", "0091-9876543210"]:
        assert normalize_phone(raw) == expected, raw
    assert normalize_phone("abc") is None


def test_address_abbreviations():
    a = normalize_address("12 MG Road, Patna")
    b = normalize_address("12 Mahatma Gandhi Road Patna")
    c = normalize_address("12, M.G. Road, Patna")
    assert a == b == c == "12 mg rd patna"
    assert normalize_address("5 Park Street") == "5 park st"


def test_dob_formats():
    assert normalize_dob("1988-05-14") == "1988-05-14"
    assert normalize_dob("14/05/1988") == "1988-05-14"
    assert normalize_dob("14-05-1988") == "1988-05-14"
    assert normalize_dob("not a date") is None
    assert normalize_dob(None) is None


def test_soundex():
    assert soundex("Sharma") == soundex("Sharmah") == "S650"
    assert soundex("Verma") == soundex("Varma")
    assert soundex("") is None


def test_normalize_record_keeps_original_and_derived():
    rec = normalize_record({"name": "RAHUL SHARMA", "email": "Rahul.Sharma@gmail.com", "phone": "+91 9876543210",
                            "address": "12 Mahatma Gandhi Road Patna", "date_of_birth": "14/05/1988", "city": "Patna"})
    assert rec["original"]["name"] == "RAHUL SHARMA"
    assert rec["norm"]["name"] == "rahul sharma"
    assert rec["norm"]["phone"] == "9876543210"
    assert rec["norm"]["dob"] == "1988-05-14"
    assert rec["derived"]["surname"] == "sharma"
    assert rec["derived"]["first_token"] == "rahul"
    assert rec["derived"]["surname_soundex"] == "S650"
    assert rec["derived"]["email_domain"] == "gmail.com"
