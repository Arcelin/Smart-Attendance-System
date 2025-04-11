import cv2
import time

def test_camera():
    print("Starting camera test...")
    
    # Try to open the camera
    cap = cv2.VideoCapture(0)
    
    # Check if camera opened successfully
    if not cap.isOpened():
        print("Failed to open camera!")
        return False
    
    print("Camera opened successfully!")
    
    # Read a few frames
    for i in range(5):
        ret, frame = cap.read()
        if not ret:
            print(f"Failed to read frame {i}")
            cap.release()
            return False
        
        print(f"Successfully read frame {i}, shape: {frame.shape}")
        time.sleep(0.5)
    
    # Release the camera
    cap.release()
    print("Camera test completed successfully!")
    return True

if __name__ == "__main__":
    test_camera() 