import cv2
import numpy as np
import os
import sqlite3
import datetime

# Path to the database
DB_PATH = 'face_attendance.db'

# Ensure faces directory exists
UPLOAD_FOLDER = 'static/faces'

# Initialize face detector
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

def get_db_connection():
    """Connect to the SQLite database"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def load_students(class_id, subject_id=None, subject_type=None):
    """Load students from database with face images"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get students based on subject type
        if subject_type == 'main':
            # Main subjects are taken by all students in the class
            cursor.execute("SELECT * FROM students WHERE class_id = ?", (class_id,))
        elif subject_type == 'elective' and subject_id:
            # Elective subjects are taken only by students who chose them
            cursor.execute("SELECT * FROM students WHERE class_id = ? AND elective_subject_id = ?", 
                           (class_id, subject_id))
        else:
            # Default to all students in the class
            cursor.execute("SELECT * FROM students WHERE class_id = ?", (class_id,))
        
        students = cursor.fetchall()
        
        # Load face images for students
        students_with_faces = []
        for student in students:
            if student['image_path'] and os.path.exists(student['image_path']):
                try:
                    student_img = cv2.imread(student['image_path'])
                    if student_img is not None:
                        students_with_faces.append({
                            'id': student['id'],
                            'name': student['name'],
                            'roll_number': student['roll_number'],
                            'image': student_img
                        })
                except Exception as e:
                    print(f"Error loading student image: {str(e)}")
        
        cursor.close()
        conn.close()
        
        return students_with_faces
    
    except Exception as e:
        print(f"Error loading students: {str(e)}")
        return []

def mark_attendance(student_ids, subject_id, subject_type):
    """Mark attendance for recognized students"""
    if not student_ids:
        return False
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        today = datetime.date.today().isoformat()
        now = datetime.datetime.now().time().isoformat()
        
        for student_id in student_ids:
            # Check if attendance already recorded
            cursor.execute(
                "SELECT * FROM attendance WHERE student_id = ? AND date = ? AND subject_id = ? AND subject_type = ?",
                (student_id, today, subject_id, subject_type)
            )
            
            if cursor.fetchone() is None:
                # Insert new attendance record
                cursor.execute(
                    "INSERT INTO attendance (student_id, subject_id, subject_type, date, time, status) VALUES (?, ?, ?, ?, ?, ?)",
                    (student_id, subject_id, subject_type, today, now, 'present')
                )
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return True
    
    except Exception as e:
        print(f"Error marking attendance: {str(e)}")
        return False

def detect_faces_and_mark_attendance(class_id, subject_id, subject_type):
    """Run face detection and mark attendance for recognized students"""
    print(f"Starting face detection for class_id={class_id}, subject_id={subject_id}, subject_type={subject_type}")
    
    # Load students data
    students = load_students(class_id, subject_id, subject_type)
    print(f"Loaded {len(students)} student images for recognition")
    
    # Open camera
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Failed to open camera!")
        return
    
    recognized_ids = []
    
    try:
        # Create a window for display
        cv2.namedWindow("Face Recognition", cv2.WINDOW_NORMAL)
        
        while True:
            # Read a frame
            ret, frame = cap.read()
            if not ret:
                print("Failed to read frame!")
                break
            
            # Create a copy for display
            display_frame = frame.copy()
            
            # Convert to grayscale
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.equalizeHist(gray)
            
            # Detect faces
            faces = face_cascade.detectMultiScale(gray, 1.1, 5, minSize=(30, 30))
            
            # Process each detected face
            for (x, y, w, h) in faces:
                # Extract face region
                face_roi = gray[y:y+h, x:x+w]
                resized_face = cv2.resize(face_roi, (100, 100))
                
                # Find best match
                best_match = None
                best_score = float('inf')
                
                for student in students:
                    try:
                        # Process student image
                        student_img = student['image']
                        student_gray = cv2.cvtColor(student_img, cv2.COLOR_BGR2GRAY)
                        
                        # Detect face in student image
                        student_faces = face_cascade.detectMultiScale(student_gray, 1.1, 5, minSize=(30, 30))
                        
                        if len(student_faces) > 0:
                            # Get student face
                            sx, sy, sw, sh = student_faces[0]
                            student_face = student_gray[sy:sy+sh, sx:sx+sw]
                            student_face = cv2.resize(student_face, (100, 100))
                            
                            # Compare faces using Mean Squared Error
                            diff = cv2.absdiff(resized_face, student_face)
                            score = np.sum(diff**2) / (100*100)
                            
                            if score < best_score:
                                best_score = score
                                best_match = student
                    except Exception as e:
                        print(f"Error comparing faces: {str(e)}")
                
                # Draw rectangle and label
                threshold = 5000  # Adjust this value based on testing
                if best_match and best_score < threshold:
                    # Recognized face
                    cv2.rectangle(display_frame, (x, y), (x+w, y+h), (0, 255, 0), 2)
                    name_text = f"{best_match['name']} ({best_match['roll_number']})"
                    cv2.putText(display_frame, name_text, (x, y-10), 
                              cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                    
                    # Add to recognized students
                    if best_match['id'] not in recognized_ids:
                        recognized_ids.append(best_match['id'])
                else:
                    # Unknown face
                    cv2.rectangle(display_frame, (x, y), (x+w, y+h), (0, 0, 255), 2)
                    cv2.putText(display_frame, "Unknown", (x, y-10), 
                              cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
            
            # Display recognized student count
            cv2.putText(display_frame, f"Recognized: {len(recognized_ids)}/{len(students)}", 
                      (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            
            # Display instructions
            cv2.putText(display_frame, "Press 'q' to quit and mark attendance", 
                      (10, display_frame.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 0), 2)
            
            # Show frame
            cv2.imshow("Face Recognition", display_frame)
            
            # Exit on 'q' press
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
        
        # Mark attendance for recognized students
        if recognized_ids:
            success = mark_attendance(recognized_ids, subject_id, subject_type)
            if success:
                print(f"Successfully marked attendance for {len(recognized_ids)} students")
            else:
                print("Failed to mark attendance!")
    
    except Exception as e:
        print(f"Error during face detection: {str(e)}")
    
    finally:
        # Release resources
        cap.release()
        cv2.destroyAllWindows()
        print("Camera released")

if __name__ == "__main__":
    # Ask for class and subject info
    print("Face Detection and Attendance")
    print("-" * 30)
    
    try:
        class_id = int(input("Enter class ID: "))
        subject_type = input("Enter subject type (main/elective): ").lower()
        
        if subject_type not in ['main', 'elective']:
            print("Invalid subject type! Defaulting to 'main'")
            subject_type = 'main'
        
        subject_id = int(input("Enter subject ID: "))
        
        # Run face detection
        detect_faces_and_mark_attendance(class_id, subject_id, subject_type)
    
    except ValueError:
        print("Invalid input! Please enter numeric values for IDs.")
    except Exception as e:
        print(f"Error: {str(e)}") 