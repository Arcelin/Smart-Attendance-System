# Smart Drishti Face Attendance System

A modern facial recognition-based attendance management system built with Python and Flask.

## Features

- **Facial Recognition-Based Attendance**
  - Real-time face detection and recognition
  - Support for webcam-based and photo upload attendance
  - Fallback recognition methods
  
- **User Management**
  - Admin and regular user roles
  - Secure authentication system
  
- **Student Management**
  - Add, edit, and delete student profiles
  - Store student photos for facial recognition
  - Assign students to classes and elective subjects
  
- **Class & Subject Management**
  - Support for multiple departments (MCA, MBA)
  - Main and elective subject tracking
  
- **Attendance Tracking**
  - Date and time stamped records
  - Group photo analysis
  - Manual verification and attendance correction
  
- **Reporting**
  - Comprehensive attendance reports
  - Filter by date, class, and subject
  - Present/absent statistics

## Technology Stack

- **Backend**: Python, Flask
- **Database**: SQLite (local deployment) / MySQL (optional)
- **Face Detection**: OpenCV with Haar Cascade Classifier
- **Face Recognition**: OpenCV with optional face_recognition library
- **Frontend**: HTML, CSS, JavaScript with Bootstrap

## Setup and Installation

1. Clone the repository
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Run the application:
   ```
   python app_sqlite.py
   ```
4. Access the application at http://localhost:5000
5. Login with default credentials:
   - Username: admin
   - Password: admin123

## Screenshots

[Screenshots will be added soon]

## License

This project is open source and available under the [MIT License](LICENSE).

## Contributors

- Arcelin

## Acknowledgments

- OpenCV for facial recognition capabilities
- Flask for web framework
- Bootstrap for UI components 