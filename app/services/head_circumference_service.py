import torch
import numpy as np
import cv2
import os
import traceback
from torchvision import transforms
from app.models.modelCSM import CSM
from PIL import Image
from flask import url_for
import base64
from io import BytesIO


def generate_mask_and_circumference(model, image_tensor):
    try:
        print("Generating mask and calculating head circumference...")
        with torch.no_grad():
            output = model(image_tensor)
        
        # Assuming the model output is a tensor representing the mask
        mask_image = output[0]  # Adjust based on your model's output format

        # Convert tensor to NumPy array
        mask_image = mask_image.squeeze().cpu().numpy()  # Remove batch and channel dimensions

        # Convert mask to 8-bit format
        mask_image = (mask_image * 255).astype(np.uint8)  # Convert mask to 8-bit image

        # Apply edge detection
        edge_img = mcc_edge(mask_image)

        # Fit an ellipse to the edge-detected image
        xc, yc, theta, a, b = ellip_fit(edge_img)
        print(f"Ellipse parameters: xc={xc}, yc={yc}, theta={theta}, a={a}, b={b}")
        # Calculate circumference from ellipse parameters
        u=8
        xc = (xc + 0.5) * u - 0.5
        yc = (yc + 0.5) * u - 0.5
        a = a * u
        b = b * u
        print(f"Ellipse parameters: xc={xc}, yc={yc}, theta={theta}, a={a}, b={b}")
        #circumference = 2 * np.pi * b + 4 * (a - b)  
        circumference = 2 * np.pi * np.sqrt((a**2 + b**2) / 2)
        print(f"Calculated circumference: {circumference}")
        # Convert mask to image bytes
        mask_pil = Image.fromarray(mask_image)
        buffer = BytesIO()
        mask_pil.save(buffer, format="PNG")
        mask_image_bytes = buffer.getvalue()

        # Optional: Calculate pixel value or any other relevant value
        pixel_value = np.mean(mask_image)  # Example pixel value calculation
        print (f"pixel value {pixel_value}")
        return mask_image_bytes, circumference, pixel_value

    except Exception as e:
        print(f"Error generating mask and circumference: {str(e)}")
        raise


# Load the model
def load_model():
    try:
        print("Loading model...")
        model_path = 'app/models/test_model.pth'
        
        model = CSM()  
        state_dict = torch.load(model_path, map_location=torch.device('cpu'))
        model.load_state_dict(state_dict)
        model.eval()
        
        print("Model loaded successfully.")
        return model
    except Exception as e:
        print(f"Error loading model: {str(e)}")
        traceback.print_exc()
        raise

# Preprocess the image
def preprocess_image(image_bytes):
    try:
        np_array = np.frombuffer(image_bytes, np.uint8)
        image = cv2.imdecode(np_array, cv2.IMREAD_GRAYSCALE)

        if image is None:
            raise ValueError("Image decoding failed")

        desired_size = (192, 128)
        resized_image = cv2.resize(image, desired_size)
        normalized_image = resized_image / 255.0
        processed_image = np.expand_dims(normalized_image, axis=0)  # Add channel dimension
        processed_image = np.expand_dims(processed_image, axis=0)  # Add batch dimension
        processed_image = torch.tensor(processed_image, dtype=torch.float32)

        return processed_image
    except Exception as e:
        print(f"Error during image preprocessing: {str(e)}")
        traceback.print_exc()
        return None


def calculate_circumference_from_mask(mask_image):
    """
    Calculates the head circumference from the given mask image.

    Args:
        mask_image (np.ndarray): The mask image as a numpy array.

    Returns:
        float: The calculated head circumference in pixels.
    """

    try:
        # Ensure mask_image is a numpy array
        if isinstance(mask_image, torch.Tensor):
            mask_image = mask_image.detach().cpu().squeeze().numpy()
        elif not isinstance(mask_image, np.ndarray):
            raise TypeError("Expected mask_image to be a numpy array or PyTorch tensor")

        # Convert mask image to uint8 if not already
        if mask_image.dtype != np.uint8:
            mask_image = (mask_image * 255).astype(np.uint8)

        # Find contours in the mask
        contours, _ = cv2.findContours(mask_image, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if not contours:
            raise ValueError("No contours found in mask image")

        # Assuming the largest contour is the head
        largest_contour = max(contours, key=cv2.contourArea)

        # Calculate circumference from the largest contour
        circumference = cv2.arcLength(largest_contour, closed=True)

        return circumference

    except Exception as e:
        print(f"Error calculating circumference from mask: {e}")
        raise

# Save mask image and return URL
def save_mask(mask_image, file_name):
    try:
        mask_path = os.path.join('static', 'masks', file_name.replace('.jpg', '_mask.png'))
        os.makedirs(os.path.dirname(mask_path), exist_ok=True)
        cv2.imwrite(mask_path, mask_image)
        return url_for('static', filename=f'masks/{file_name.replace(".jpg", "_mask.png")}', _external=True)
    except Exception as e:
        print(f"Error saving mask image: {str(e)}")
        traceback.print_exc()
        return None

# Main function to calculate circumference
def calculate_circumference(image_bytes):
    try:
        processed_image = preprocess_image(image_bytes)
        
        if processed_image is None:
            raise ValueError("Image processing failed")

        model = load_model()
        mask_image, circumference = generate_mask_and_circumference(model, processed_image)

        if mask_image is not None:
            mask_image_np = mask_image.detach().cpu().squeeze().numpy() * 255
            mask_image_np = mask_image_np.astype(np.uint8)
            return circumference, save_mask(mask_image_np, 'temp_image.jpg')
        else:
            return None, None
    except Exception as e:
        print(f"Error during processing: {str(e)}")
        traceback.print_exc()
        return None, None


def mcc_edge(mask_image):
    """
    Applies edge detection using the Canny method.

    Args:
        mask_image (np.ndarray): The mask image as a numpy array.

    Returns:
        np.ndarray: The edge-detected image.
    """
    if not isinstance(mask_image, np.ndarray):
        raise TypeError("Expected mask_image to be a numpy array")

    # Ensure the mask image is in uint8 format
    if mask_image.dtype != np.uint8:
        mask_image = (mask_image * 255).astype(np.uint8)

    # Apply Canny edge detection
    edges = cv2.Canny(mask_image, 100, 200)
    return edges

def ellip_fit(edge_image):
    """
    Fits an ellipse to the edge-detected image.

    Args:
        edge_image (np.ndarray): The edge-detected image.

    Returns:
        tuple: The ellipse parameters (xc, yc, theta, a, b)
    """
    if not isinstance(edge_image, np.ndarray):
        raise TypeError("Expected edge_image to be a numpy array")

    # Find contours
    contours, _ = cv2.findContours(edge_image, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        raise ValueError("No contours found in edge image")

    # Assume the largest contour is the object of interest
    largest_contour = max(contours, key=cv2.contourArea)

    # Fit an ellipse to the largest contour
    if len(largest_contour) < 5:
        raise ValueError("Not enough points to fit an ellipse")

    ellipse = cv2.fitEllipse(largest_contour)
    xc, yc = ellipse[0]  # Center of the ellipse
    (a, b) = ellipse[1]  
    theta = ellipse[2]  # Rotation angle
    if a < b:
        t = b
        b = a
        a = t
        theta = theta + 0.5 * np.pi

    return xc, yc, theta, a, b


def calculate_fetal_age(head_circumference_cm):
    if head_circumference_cm < 8.00: return 'Fetus is less than 8 Menstrual Weeks'
    if head_circumference_cm >= 8.00 and head_circumference_cm <= 9.00: return '13 Weeks'
    if head_circumference_cm > 9.00 and head_circumference_cm <= 10.49: return '14 Weeks'
    if head_circumference_cm > 10.50 and head_circumference_cm <= 12.49: return '15 Weeks'
    if head_circumference_cm > 12.50 and head_circumference_cm <= 13.49: return '16 Weeks'
    if head_circumference_cm > 13.50 and head_circumference_cm <= 14.99: return '17 Weeks'
    if head_circumference_cm > 15.00 and head_circumference_cm <= 16.49: return '18 Weeks'
    if head_circumference_cm > 16.50 and head_circumference_cm <= 17.49: return '19 Weeks'
    if head_circumference_cm > 17.50 and head_circumference_cm <= 18.99: return '20 Weeks'
    if head_circumference_cm > 19.00 and head_circumference_cm <= 19.99: return '21 Weeks'
    if head_circumference_cm > 20.00 and head_circumference_cm <= 20.99: return '22 Weeks'
    if head_circumference_cm > 21.00 and head_circumference_cm <= 22.49: return '23 Weeks'
    if head_circumference_cm > 22.50 and head_circumference_cm <= 22.99: return '24 Weeks'
    if head_circumference_cm >= 23.00 and head_circumference_cm <= 23.99: return '25 Weeks'
    if head_circumference_cm > 24.00 and head_circumference_cm <= 24.79: return '26 Weeks'
    if head_circumference_cm > 24.80 and head_circumference_cm <= 25.60: return '27 Weeks'
    if head_circumference_cm > 25.61 and head_circumference_cm <= 26.75: return '28 Weeks'
    if head_circumference_cm > 26.76 and head_circumference_cm <= 27.75: return '29 Weeks'
    if head_circumference_cm > 27.76 and head_circumference_cm <= 28.85: return '30 Weeks'
    if head_circumference_cm > 28.86 and head_circumference_cm <= 29.60: return '31 Weeks'
    if head_circumference_cm > 29.61 and head_circumference_cm <= 30.40: return '32 Weeks'
    if head_circumference_cm > 30.41 and head_circumference_cm <= 31.20: return '33 Weeks'
    if head_circumference_cm > 31.21 and head_circumference_cm <= 31.80: return '34 Weeks'
    if head_circumference_cm > 31.81 and head_circumference_cm <= 32.50: return '35 Weeks'
    if head_circumference_cm > 32.51 and head_circumference_cm <= 33.00: return '36 Weeks'
    if head_circumference_cm > 33.01 and head_circumference_cm <= 33.70: return '37 Weeks'
    if head_circumference_cm > 33.71 and head_circumference_cm <= 34.20: return '38 Weeks'
    if head_circumference_cm > 34.21 and head_circumference_cm <= 35.00: return '39 Weeks'
    if head_circumference_cm > 35.00 and head_circumference_cm <= 36.00: return '40 Weeks'
    return 'Abnormal'


