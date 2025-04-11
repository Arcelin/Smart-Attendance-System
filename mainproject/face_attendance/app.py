import cv2
import os
import datetime
import mysql.connector
from flask import Flask, render_template, request, redirect, url_for, flash, session, Response, jsonify
import numpy as np

# Initialize Flask app
app = Flask(__name__)
app.secret_key = 'face_attendance_secret_key'

# MySQL Configuration
db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': '',  # Change this to your MySQL password
    'database': 'face_attendance'
}

# Ensure directory for storing student face images exists
UPLOAD_FOLDER = 'static/faces'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Initialize face detector
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

# Database helper functions
def get_db_connection():
    return mysql.connector.connect(**db_config)

def init_database():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create tables if they don't exist
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS students (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        roll_number VARCHAR(20) NOT NULL UNIQUE,
        class_id INT NOT NULL,
        image_path VARCHAR(255)
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS classes (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        department VARCHAR(100) NOT NULL
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS attendance (
        id INT AUTO_INCREMENT PRIMARY KEY,
        student_id INT NOT NULL,
        date DATE NOT NULL,
        time TIME NOT NULL,
        status ENUM('present', 'absent') NOT NULL,
        FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
    )
    ''')
    
    # Insert default class if none exist
    cursor.execute("SELECT COUNT(*) FROM classes")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO classes (name, department) VALUES (%s, %s)", 
                      ("Default Class", "Computer Science"))
    
    conn.commit()
    cursor.close()
    conn.close()

# Initialize the database when the app starts
init_database()

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/students')
def students():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Get all students with their class name
    cursor.execute('''
    SELECT s.*, c.name as class_name 
    FROM students s 
    JOIN classes c ON s.class_id = c.id
    ''')
    
    students = cursor.fetchall()
    
    # Get all classes for the add student form
    cursor.execute("SELECT * FROM classes")
    classes = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('students.html', students=students, classes=classes)

@app.route('/add_student', methods=['GET', 'POST'])
def add_student():
    if request.method == 'POST':
        name = request.form['name']
        roll_number = request.form['roll_number']
        class_id = request.form['class_id']
        
        # Check if a face image was uploaded
        if 'face_image' not in request.files:
            flash('No face image provided', 'danger')
            return redirect(request.url)
        
        file = request.files['face_image']
        
        if file.filename == '':
            flash('No selected file', 'danger')
            return redirect(request.url)
        
        if file:
            # Save the image
            filename = f"{roll_number}.jpg"
            file_path = os.path.join(UPLOAD_FOLDER, filename)
            file.save(file_path)
            
            # Detect if there is a face in the image
            img = cv2.imread(file_path)
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, 1.1, 4)
            
            if len(faces) == 0:
                # No face detected
                os.remove(file_path)
                flash('No face detected in the image. Please upload a clear face image.', 'danger')
                return redirect(request.url)
            
            # If a face is detected, save to database
            conn = get_db_connection()
            cursor = conn.cursor()
            
            try:
                cursor.execute(
                    "INSERT INTO students (name, roll_number, class_id, image_path) VALUES (%s, %s, %s, %s)",
                    (name, roll_number, class_id, file_path)
                )
                conn.commit()
                flash('Student added successfully!', 'success')
            except mysql.connector.IntegrityError:
                flash('Roll number already exists!', 'danger')
            finally:
                cursor.close()
                conn.close()
                
            return redirect(url_for('students'))
    
    # If GET request or form submission failed
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM classes")
    classes = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return render_template('add_student.html', classes=classes)

@app.route('/take_attendance')
def take_attendance():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Get all classes
    cursor.execute("SELECT * FROM classes")
    classes = cursor.fetchall()
    
    # Get all main subjects
    cursor.execute("SELECT * FROM main_subjects")
    main_subjects = cursor.fetchall()
    
    # Get all elective subjects
    cursor.execute("SELECT * FROM elective_subjects")
    elective_subjects = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('take_attendance.html', 
                          classes=classes, 
                          main_subjects=main_subjects,
                          elective_subjects=elective_subjects)

@app.route('/set_subject/<int:class_id>/<int:subject_id>/<subject_type>')
def set_subject(class_id, subject_id, subject_type):
    # Store subject info in session
    session['class_id'] = class_id
    session['subject_id'] = subject_id
    session['subject_type'] = subject_type
    
    return 'Subject set successfully'

@app.route('/check_class_students/<int:class_id>')
def check_class_students(class_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Count students in the class
    cursor.execute("SELECT COUNT(*) as count FROM students WHERE class_id = %s", (class_id,))
    result = cursor.fetchone()
    
    cursor.close()
    conn.close()
    
    if result and result['count'] > 0:
        return jsonify({"success": True, "count": result['count']})
    else:
        return jsonify({"success": False, "message": "No students found in this class"})

@app.route('/video_feed/<int:class_id>')
def video_feed(class_id):
    # Get subject info from session at request time
    subject_id = session.get('subject_id')
    subject_type = session.get('subject_type')
    
    def generate_frames():
        # Store the subject info from the request context
        current_subject_id = subject_id
        current_subject_type = subject_type
        
        # Open webcam
        cap = cv2.VideoCapture(0)
        
        if not cap.isOpened():
            print("Failed to open camera!")
            # Return error frames
            for _ in range(3):
                error_frame = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(error_frame, "Camera initialization failed", (50, 200), 
                           cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                
                ret, buffer = cv2.imencode('.jpg', error_frame)
                error_frame_bytes = buffer.tobytes()
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + error_frame_bytes + b'\r\n')
            return
            
        while True:
            success, frame = cap.read()
            if not success:
                break
            
            try:
                # Process the frame to detect faces and mark attendance
                # Pass the captured subject values
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = face_cascade.detectMultiScale(gray, 1.1, 4)
                
                # Draw rectangle around faces for display
                for (x, y, w, h) in faces:
                    cv2.rectangle(frame, (x, y), (x+w, y+h), (255, 0, 0), 2)
                
                # Mark attendance for detected faces
                if len(faces) > 0:
                    today = datetime.date.today()
                    now = datetime.datetime.now().time()
                    
                    # Get all students from the selected class
                    conn = get_db_connection()
                    cursor = conn.cursor(dictionary=True)
                    cursor.execute("SELECT * FROM students WHERE class_id = %s", (class_id,))
                    students = cursor.fetchall()
                    
                    for student in students:
                        # Check if attendance already recorded for today
                        cursor.execute(
                            "SELECT * FROM attendance WHERE student_id = %s AND date = %s AND subject_id = %s AND subject_type = %s",
                            (student['id'], today, current_subject_id, current_subject_type)
                        )
                        
                        if cursor.fetchone() is None:
                            cursor.execute(
                                "INSERT INTO attendance (student_id, subject_id, subject_type, date, time, status) VALUES (%s, %s, %s, %s, %s, %s)",
                                (student['id'], current_subject_id, current_subject_type, today, now, 'present')
                            )
                    
                    conn.commit()
                    cursor.close()
                    conn.close()
            except Exception as e:
                print(f"Error in face detection: {str(e)}")
            
            # Convert to jpeg format
            ret, buffer = cv2.imencode('.jpg', frame)
            processed_frame = buffer.tobytes()
            
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + processed_frame + b'\r\n')
        
        cap.release()
    
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/fallback_feed/<int:class_id>')
def fallback_feed(class_id):
    # Get subject info from session
    subject_id = session.get('subject_id')
    subject_type = session.get('subject_type')
    
    # Validate parameters
    if not subject_id or not subject_type:
        flash('Error: Subject information is required', 'danger')
        return redirect(url_for('take_attendance'))
    
    # Handle the manual attendance marking here
    # For simplicity in the fallback mode, mark all students as present
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Get students based on subject type
    if subject_type == 'main':
        # All students in the class take main subjects
        cursor.execute("SELECT * FROM students WHERE class_id = %s", (class_id,))
    else:
        # Only students who selected this elective
        cursor.execute("SELECT * FROM students WHERE class_id = %s AND elective_subject_id = %s", 
                      (class_id, subject_id))
    
    students = cursor.fetchall()
    
    # Mark all students present
    today = datetime.date.today()
    now = datetime.datetime.now().time()
    
    for student in students:
        # Check if attendance already recorded for today
        cursor.execute(
            "SELECT * FROM attendance WHERE student_id = %s AND date = %s AND subject_id = %s AND subject_type = %s",
            (student['id'], today, subject_id, subject_type)
        )
        
        if cursor.fetchone() is None:
            cursor.execute(
                "INSERT INTO attendance (student_id, subject_id, subject_type, date, time, status) VALUES (%s, %s, %s, %s, %s, %s)",
                (student['id'], subject_id, subject_type, today, now, 'present')
            )
    
    conn.commit()
    cursor.close()
    conn.close()
    
    flash('Attendance marked successfully using fallback method', 'success')
    return redirect(url_for('process_attendance', class_id=class_id))

@app.route('/process_attendance', methods=['POST'])
def process_attendance():
    class_id = request.form['class_id']
    
    # Get class name
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT name FROM classes WHERE id = %s", (class_id,))
    class_name = cursor.fetchone()['name']
    
    # Get today's attendance for this class
    today = datetime.date.today()
    cursor.execute('''
    SELECT s.id, s.name, s.roll_number, a.status
    FROM students s
    LEFT JOIN attendance a ON s.id = a.student_id AND a.date = %s
    WHERE s.class_id = %s
    ''', (today, class_id))
    
    attendance_results = cursor.fetchall()
    
    # Count present students
    present_count = 0
    for student in attendance_results:
        if student['status'] == 'present':
            present_count += 1
    
    cursor.close()
    conn.close()
    
    return render_template('attendance_result.html', 
                          class_name=class_name,
                          date=today.strftime("%B %d, %Y"),
                          attendance_results=attendance_results,
                          present_count=present_count,
                          total_count=len(attendance_results))

@app.route('/view_attendance')
def view_attendance():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Get all classes
    cursor.execute("SELECT * FROM classes")
    classes = cursor.fetchall()
    
    # Get distinct dates with attendance records
    cursor.execute("SELECT DISTINCT date FROM attendance ORDER BY date DESC")
    dates = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('view_attendance.html', classes=classes, dates=dates)

@app.route('/attendance_report', methods=['POST'])
def attendance_report():
    class_id = request.form['class_id']
    date = request.form['date']
    subject_id = request.form.get('subject_id')
    subject_type = request.form.get('subject_type')
    
    if not subject_id or not subject_type:
        flash('Error: Subject information is required', 'danger')
        return redirect(url_for('view_attendance'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Get class name
    cursor.execute("SELECT name FROM classes WHERE id = %s", (class_id,))
    class_name = cursor.fetchone()['name']
    
    # Get subject name
    if subject_type == 'main':
        cursor.execute("SELECT name FROM main_subjects WHERE id = %s", (subject_id,))
    else:
        cursor.execute("SELECT name FROM elective_subjects WHERE id = %s", (subject_id,))
    
    subject_result = cursor.fetchone()
    if not subject_result:
        flash('Error: Invalid subject selected', 'danger')
        return redirect(url_for('view_attendance'))
    
    subject_name = subject_result['name']
    
    # Get enrollment statistics
    total_class_students = 0
    enrolled_students = 0
    
    # Count total students in class
    cursor.execute("SELECT COUNT(*) as count FROM students WHERE class_id = %s", (class_id,))
    total_class_students = cursor.fetchone()['count']
    
    # Count enrolled students based on subject type
    if subject_type == 'main':
        # All students in the class are enrolled in main subjects
        enrolled_students = total_class_students
    else:
        # Only students who selected this elective are enrolled
        cursor.execute("SELECT COUNT(*) as count FROM students WHERE class_id = %s AND elective_subject_id = %s", 
                     (class_id, subject_id))
        enrolled_students = cursor.fetchone()['count']
    
    # Get attendance for the selected date, class, and subject
    if subject_type == 'main':
        # For main subjects, check attendance for all students in class
        cursor.execute('''
        SELECT s.id, s.name, s.roll_number, a.status
        FROM students s
        LEFT JOIN attendance a ON s.id = a.student_id AND a.date = %s AND a.subject_id = %s AND a.subject_type = %s
        WHERE s.class_id = %s
        ''', (date, subject_id, subject_type, class_id))
    else:
        # For elective subjects, only show students enrolled in this elective
        cursor.execute('''
        SELECT s.id, s.name, s.roll_number, a.status
        FROM students s
        LEFT JOIN attendance a ON s.id = a.student_id AND a.date = %s AND a.subject_id = %s AND a.subject_type = %s
        WHERE s.class_id = %s AND s.elective_subject_id = %s
        ''', (date, subject_id, subject_type, class_id, subject_id))
    
    attendance_results = cursor.fetchall()
    
    # Count present students
    present_count = 0
    for student in attendance_results:
        if student['status'] == 'present':
            present_count += 1
    
    cursor.close()
    conn.close()
    
    formatted_date = datetime.datetime.strptime(date, '%Y-%m-%d').strftime("%B %d, %Y")
    
    return render_template('attendance_report.html', 
                          class_name=class_name,
                          subject_name=subject_name,
                          subject_type=subject_type,
                          class_id=class_id,
                          date=formatted_date,
                          attendance_results=attendance_results,
                          present_count=present_count,
                          total_count=len(attendance_results),
                          total_class_students=total_class_students,
                          enrolled_students=enrolled_students)

if __name__ == '__main__':
    app.run(debug=True) 