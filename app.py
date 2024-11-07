from flask import Flask, request, jsonify, render_template
import requests
from bs4 import BeautifulSoup
from collections import defaultdict
from datetime import datetime
import re

app = Flask(__name__)

# Define the base URL of the schedule page
base_url = "https://web.csulb.edu/depts/enrollment/registration/class_schedule/Fall_2024/By_Subject/"  # Replace with the actual URL

def get_subject_links():
    """Fetch the main page and extract subject links."""
    main_url = base_url + "index.html"  # Modify as needed if it's different
    response = requests.get(main_url)
    soup = BeautifulSoup(response.text, 'html.parser')

    subject_links = {}
    block = soup.find('div', class_='indexList')
    for ul in block.find_all("ul"):
        for li in ul.find_all("li"):
            link = li.find("a")
            if link:
                subject_name = link.text.strip()
                subject_href = link.get("href")
                subject_links[subject_name] = base_url + subject_href
    return subject_links

def get_class_data(subject_url):
    """Fetch a subject's page and extract class data."""
    response = requests.get(subject_url)
    soup = BeautifulSoup(response.text, 'html.parser')

    # Create a nested defaultdict to store courses by location and day
    courses_by_location = defaultdict(lambda: defaultdict(list))

    for course_block in soup.find_all("div", class_="courseBlock"):
        # Parse the section table
        for row in course_block.find_all("tr")[1:]:  # Skip header row
            cols = row.find_all("td")
            if len(cols) > 0:
                days = cols[5].text.strip()
                time = cols[6].text.strip()
                location = cols[8].text.strip()

                # Skip courses that are "NA" (online-only by days or time) or "ONLINE-ONLY" by location
                if days != "NA" and time != "NA" and location != "ONLINE-ONLY" and location != 'NA':
                    # Group courses by day within each location
                    courses_by_location[location][days].append(time)

    return courses_by_location

def sort_times_by_day(building_courses):
    """Sort courses in each day by their start time within a building."""
    sorted_courses = {}
    for day, times in building_courses.items():
        # Filter and parse times only if valid
        valid_times = [t for t in times if is_valid_time_format(t.split("-")[0])]
        invalid_times = [t for t in times if not is_valid_time_format(t.split("-")[0])]
        
        # Log any invalid times for debugging
        if invalid_times:
            print(f"Invalid times found for day {day}: {invalid_times}")

        # Sort valid times by the start time
        sorted_times = sorted(valid_times, key=lambda x: parse_time(x.split("-")[0]))
        sorted_courses[day] = sorted_times
    return sorted_courses

def save_to_file(all_courses_by_location, filename="class_schedule.txt"):
    """Save the collected class data by location and day to a text file."""
    with open(filename, "w") as file:
        for location, days_data in all_courses_by_location.items():
            file.write(f"Location: {location}\n")
            for day, times in days_data.items():
                file.write(f"  {day}:\n")
                for time in times:
                    file.write(f"    - {time}\n")
            file.write("\n")  # Add an empty line between locations

def load_from_file(filename="class_schedule.txt"):
    """Load class data from a text file into a nested dictionary."""
    all_courses_by_location = defaultdict(lambda: defaultdict(list))
    current_location = None

    with open(filename, "r") as file:
        for line in file:
            line = line.strip()
            if line.startswith("Location:"):
                current_location = line.split(": ")[1]
            elif line and line[0] != "-":
                current_day = line.strip(":")
            elif line.startswith("-"):
                time = line.split("- ")[1]
                all_courses_by_location[current_location][current_day].append(time)

    return all_courses_by_location

def is_valid_time_format(time_str):
    """Check if time format matches expected '%I:%M%p' or '%I%p'."""
    match = re.match(r"^\d{1,2}(:\d{2})?(AM|PM)$", time_str)
    return bool(match)

def parse_time(time_str):
    """Parse time string, handling both '%I:%M%p' and '%I%p' formats."""
    if ':' in time_str:
        return datetime.strptime(time_str, "%I:%M%p")  # Format like '10:00AM'
    else:
        return datetime.strptime(time_str, "%I%p")  # Format like '10AM'

def normalize_time(time_str):
    """Normalize a time string to ensure '%I:%M%p' format."""
    # Split start and end time by '-'
    parts = time_str.split("-")
    start_str, end_str = parts[0], parts[1]

    # Add :00 if missing minutes
    if ":" not in start_str:
        start_str += ":00"
    if ":" not in end_str:
        end_str += ":00"

    # Add AM/PM if missing
    if "AM" not in start_str and "PM" not in start_str:
        start_str += "AM"  # Assume AM for the start time if missing
    if "AM" not in end_str and "PM" not in end_str:
        # Determine if end time should be PM based on comparison
        start_time = datetime.strptime(start_str, "%I:%M%p")
        end_time = datetime.strptime(end_str, "%I:%M%p")
        
        # If start time is later than end time, the end time is in PM
        if start_time >= end_time:
            end_str += "PM"
        else:
            end_str += "AM"

    return start_str, end_str

def day_matches(input_day, schedule_day):
    """Check if input day is part of the scheduled days string."""
    # Return True if the input day (like "Tu") is in schedule_day (like "TuThu")
    return input_day in schedule_day

def find_open_rooms(courses_by_location, building, day, start_time, end_time):
    """Find open rooms in a specified building prefix within a time range on a specified day."""
    open_rooms = []
    input_start = parse_time(start_time)
    input_end = parse_time(end_time)

    # Iterate over all rooms (locations) in the data
    for room, days_data in courses_by_location.items():
        # Check if the room's prefix matches the specified building
        build , num = room.split("-")
        if build != building:
            continue  # Skip rooms that do not belong to the specified building prefix

        # Check if the room has any scheduled classes on the specified day
        room_free = True
        for schedule_day, times in days_data.items():
            # Only check times if the schedule day matches the input day
            if day_matches(day, schedule_day):
                for time in times:
                    # Normalize time range and parse it
                    class_start_str, class_end_str = normalize_time(time)
                    class_start = parse_time(class_start_str)
                    class_end = parse_time(class_end_str)

                    # Check for overlap with the specified time range
                    if not (input_end <= class_start or input_start >= class_end):
                        room_free = False
                        break  # Stop checking times if overlap is found
                if not room_free:
                    break  # Stop checking days if overlap is found

        if room_free:
            open_rooms.append(room)

    return open_rooms

@app.route('/')
def landing():
    return render_template("index.html")
    
@app.route("/find_open_rooms", methods=["POST"])
def find_open_rooms_api():
    data = request.json
    building = data["building"]
    day = data["day"]
    start_time = data["start_time"]
    end_time = data["end_time"]

    # Load class data
    try:
        all_courses_by_location = load_from_file()
    except FileNotFoundError:
        all_courses_by_location = scrape_and_save_data()

    open_rooms = find_open_rooms(all_courses_by_location, building, day, start_time, end_time)
    return jsonify({"open_rooms": open_rooms})

def scrape_and_save_data():
    # Combine scraping and saving into one function
    subject_links = get_subject_links()
    all_courses_by_location = defaultdict(lambda: defaultdict(list))

    for subject_name, subject_url in subject_links.items():
        courses_by_location = get_class_data(subject_url)
        for location, days_data in courses_by_location.items():
            for day, times in days_data.items():
                all_courses_by_location[location][day].extend(times)
    
    save_to_file(all_courses_by_location)
    return all_courses_by_location

if __name__ == "__main__":
    app.run(debug=True)
