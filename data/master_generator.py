"""Synthetic MASTER data generator (Indian-style names and addresses).

Everything here is invented.  No real customer information is used.
Generation is seeded, so the same seed always produces the same records.

The worked example used throughout the application
(Rahul Sharma, 9876543210, rahul.sharma@gmail.com, 12 MG Road, Patna)
is always inserted so that it can be searched for in demonstrations.
"""
from __future__ import annotations

import random
from datetime import date, timedelta

FIRST_NAMES_MALE = [
    "Rahul", "Amit", "Vikram", "Suresh", "Rajesh", "Anil", "Sanjay", "Arjun", "Rohit", "Manish",
    "Deepak", "Nitin", "Sachin", "Ravi", "Ajay", "Vivek", "Karan", "Abhishek", "Gaurav", "Pankaj",
    "Ashok", "Prakash", "Mohit", "Varun", "Aditya", "Harish", "Kunal", "Naveen", "Siddharth", "Tarun",
    "Yash", "Ankit", "Sandeep", "Rakesh", "Mukesh", "Dinesh", "Vinod", "Alok", "Nikhil", "Saurabh",
]
FIRST_NAMES_FEMALE = [
    "Priya", "Neha", "Anjali", "Pooja", "Sneha", "Kavita", "Sunita", "Ritu", "Meena", "Divya",
    "Swati", "Shreya", "Nisha", "Aarti", "Preeti", "Komal", "Deepika", "Ananya", "Megha", "Shweta",
    "Rekha", "Sapna", "Jyoti", "Payal", "Isha", "Tanvi", "Radhika", "Kiran", "Lakshmi", "Geeta",
    "Manisha", "Suman", "Vandana", "Archana", "Bhavna", "Simran", "Pallavi", "Rashmi", "Seema", "Ruchi",
]
SURNAMES = [
    "Sharma", "Verma", "Singh", "Kumar", "Gupta", "Mishra", "Yadav", "Jha", "Pandey", "Tiwari",
    "Agarwal", "Mehta", "Patel", "Shah", "Joshi", "Chauhan", "Rathore", "Sinha", "Das", "Nair",
    "Reddy", "Rao", "Iyer", "Menon", "Pillai", "Choudhary", "Dubey", "Srivastava", "Saxena", "Bhatt",
    "Kapoor", "Malhotra", "Khanna", "Bose", "Banerjee", "Mukherjee", "Chatterjee", "Ghosh", "Kulkarni", "Deshpande",
    "Thakur", "Rawat", "Negi", "Prasad", "Ranjan", "Trivedi", "Goel", "Bansal", "Jain", "Arora",
]

# city → (state, PIN prefix)
CITIES = {
    "Patna": ("Bihar", "800"), "Mumbai": ("Maharashtra", "400"), "Delhi": ("Delhi", "110"),
    "Bengaluru": ("Karnataka", "560"), "Chennai": ("Tamil Nadu", "600"), "Kolkata": ("West Bengal", "700"),
    "Hyderabad": ("Telangana", "500"), "Pune": ("Maharashtra", "411"), "Ahmedabad": ("Gujarat", "380"),
    "Jaipur": ("Rajasthan", "302"), "Lucknow": ("Uttar Pradesh", "226"), "Kanpur": ("Uttar Pradesh", "208"),
    "Nagpur": ("Maharashtra", "440"), "Indore": ("Madhya Pradesh", "452"), "Bhopal": ("Madhya Pradesh", "462"),
    "Ranchi": ("Jharkhand", "834"), "Guwahati": ("Assam", "781"), "Chandigarh": ("Chandigarh", "160"),
    "Dehradun": ("Uttarakhand", "248"), "Bhubaneswar": ("Odisha", "751"), "Kochi": ("Kerala", "682"),
    "Surat": ("Gujarat", "395"), "Varanasi": ("Uttar Pradesh", "221"), "Gaya": ("Bihar", "823"),
    "Muzaffarpur": ("Bihar", "842"),
}

STREETS = [
    "MG Road", "Station Road", "Gandhi Nagar", "Nehru Street", "Park Street", "Boring Road", "Fraser Road",
    "Bailey Road", "Kankarbagh Main Road", "Rajendra Nagar", "Ashok Nagar", "Civil Lines", "Mall Road",
    "Church Street", "Brigade Road", "Residency Road", "Anna Salai", "Linking Road", "Hill Road",
    "SV Road", "Jubilee Hills Road", "Banjara Hills", "Sector 17", "Sector 22", "Vijay Nagar",
    "Lajpat Nagar", "Karol Bagh", "Rohini Sector 9", "Salt Lake Sector V", "Koramangala 5th Block",
    "Indiranagar 100 Feet Road", "Shivaji Nagar", "FC Road", "JM Road", "Satellite Road", "CG Road",
    "Tonk Road", "MI Road", "Hazratganj", "Gomti Nagar",
]
BUILDINGS = ["", "", "", "Flat 3B, Shanti Apartments, ", "House No 45, ", "2nd Floor, Krishna Tower, ", "Plot 12, ", "B-204, Sai Residency, "]
COMPANIES = [
    "Tata Consultancy Services", "Infosys Ltd", "Wipro Limited", "HDFC Bank", "ICICI Bank", "State Bank of India",
    "Reliance Industries", "Mahindra & Mahindra", "Bharti Airtel", "Larsen & Toubro", "Tech Mahindra",
    "HCL Technologies", "Axis Bank", "Kotak Mahindra Bank", "Bajaj Finance", "Asian Paints", "Hindustan Unilever",
    "ITC Limited", "Adani Enterprises", "Zomato", "Flipkart", "Paytm", "Ola Cabs", "Swiggy", "Byju's",
    "Sharma Traders Pvt Ltd", "Verma & Sons", "Gupta Textiles", "Patna Steel Works", "Sunrise Pharma Pvt Ltd",
    "Self Employed", "Government of Bihar", "Indian Railways", "Delhi Public School", "Apollo Hospitals",
]
EMAIL_DOMAINS = ["gmail.com", "gmail.com", "gmail.com", "yahoo.com", "yahoo.co.in", "outlook.com", "hotmail.com", "rediffmail.com"]

WORKED_EXAMPLE = {
    "name": "Rahul Sharma",
    "email": "rahul.sharma@gmail.com",
    "phone": "9876543210",
    "address": "12 MG Road, Patna",
    "date_of_birth": "1988-05-14",
    "company": "Tata Consultancy Services",
    "city": "Patna",
    "state": "Bihar",
    "postal_code": "800001",
}


def entity_id_for(index: int) -> str:
    """Sequential entity IDs: C00001, C00002, ..."""
    return f"C{index:05d}"


def _email_for(first: str, last: str, rng: random.Random, used: set[str]) -> str:
    patterns = [
        f"{first}.{last}", f"{first}{last}", f"{first}_{last}", f"{first[0]}{last}",
        f"{first}{rng.randint(1, 99)}", f"{first}.{last}{rng.randint(1, 999)}", f"{last}.{first}",
    ]
    for _ in range(20):
        email = f"{rng.choice(patterns)}@{rng.choice(EMAIL_DOMAINS)}".lower()
        if email not in used:
            used.add(email)
            return email
    email = f"{first}.{last}{rng.randint(1000, 99999)}@gmail.com".lower()
    used.add(email)
    return email


def _phone_for(rng: random.Random, used: set[str]) -> str:
    while True:
        phone = str(rng.choice([6, 7, 8, 9])) + "".join(str(rng.randint(0, 9)) for _ in range(9))
        if phone not in used:
            used.add(phone)
            return phone


def _dob_for(rng: random.Random) -> str:
    start = date(1955, 1, 1)
    return (start + timedelta(days=rng.randint(0, 365 * 48))).strftime("%Y-%m-%d")


def generate_person(rng: random.Random, used_emails: set[str], used_phones: set[str]) -> dict:
    first = rng.choice(FIRST_NAMES_MALE if rng.random() < 0.55 else FIRST_NAMES_FEMALE)
    last = rng.choice(SURNAMES)
    city = rng.choice(list(CITIES.keys()))
    state, pin_prefix = CITIES[city]
    street = rng.choice(STREETS)
    number = rng.randint(1, 250)
    address = f"{rng.choice(BUILDINGS)}{number} {street}, {city}"
    return {
        "name": f"{first} {last}",
        "email": _email_for(first, last, rng, used_emails),
        "phone": _phone_for(rng, used_phones),
        "address": address,
        "date_of_birth": _dob_for(rng),
        "company": rng.choice(COMPANIES),
        "city": city,
        "state": state,
        "postal_code": f"{pin_prefix}{rng.randint(1, 99):03d}",
    }


def make_twin(person: dict, rng: random.Random, used_emails: set[str], used_phones: set[str]) -> dict:
    """A different person who looks confusingly similar (same name, same city)."""
    first, last = person["name"].split(" ", 1)
    street = rng.choice(STREETS)
    return {
        **person,
        "email": _email_for(first, last, rng, used_emails),
        "phone": _phone_for(rng, used_phones),
        "address": f"{rng.randint(1, 250)} {street}, {person['city']}",
        "date_of_birth": _dob_for(rng),
        "company": rng.choice(COMPANIES),
        "postal_code": person["postal_code"][:3] + f"{rng.randint(1, 99):03d}",
    }


def generate_master(n: int, seed: int = 42, twin_pct: float = 2.0, start_index: int = 1,
                    include_example: bool = True) -> list[dict]:
    """Generate `n` synthetic master records.

    * `twin_pct` percent of records get a near-twin (same name + city, different
      identifiers) so that the "two very similar candidates" scenario exists.
    * The worked example (Rahul Sharma) is placed at position 1023 if n >= 1023,
      otherwise at position 1 – giving it entity ID C01023 in a 5,000-record demo.
    """
    rng = random.Random(seed)
    used_emails: set[str] = {WORKED_EXAMPLE["email"]}
    used_phones: set[str] = {WORKED_EXAMPLE["phone"]}
    people: list[dict] = []
    n_twins = int(round(n * twin_pct / 100))

    while len(people) < n:
        person = generate_person(rng, used_emails, used_phones)
        people.append(person)
        if n_twins > 0 and len(people) < n and rng.random() < (twin_pct / 100) * 2:
            people.append(make_twin(person, rng, used_emails, used_phones))
            n_twins -= 1
    people = people[:n]

    if include_example and n > 0:
        pos = 1022 if n >= 1023 else 0
        people[pos] = dict(WORKED_EXAMPLE)

    records = []
    for i, person in enumerate(people):
        idx = start_index + i
        records.append({"entity_id": entity_id_for(idx), **person, "source": "synthetic"})
    return records


def find_twin_pairs(records: list[dict]) -> list[tuple[dict, dict]]:
    """Pairs of master records with identical name + city (used for ambiguity demos)."""
    seen: dict[tuple[str, str], dict] = {}
    pairs = []
    for rec in records:
        key = ((rec.get("name") or "").lower(), (rec.get("city") or "").lower())
        if key in seen and rec["entity_id"] != seen[key]["entity_id"]:
            pairs.append((seen[key], rec))
        else:
            seen[key] = rec
    return pairs
