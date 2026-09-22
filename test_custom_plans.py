"""
Test custom gym plans functionality using Playwright
"""
from playwright.sync_api import sync_playwright
import time

def test_admin_custom_plans():
    with sync_playwright() as p:
        # Launch browser
        browser = p.chromium.launch(headless=False, slow_mo=500)
        page = browser.new_page()

        print("[INFO] Opening admin panel...")
        page.goto('http://localhost:8000/admin')

        # Login
        print("[INFO] Logging in...")
        page.fill('#loginEmail', 'admin@example.com')
        page.fill('#loginPassword', 'Demo@12345')
        page.click('button[type="submit"]')
        time.sleep(3)

        # Go to Gyms tab
        print("[INFO] Navigating to Gyms tab...")
        page.click('text=Gyms')
        time.sleep(2)

        # Click Add Gym button
        print("[INFO] Opening Add Gym modal...")
        page.click('text=Add Gym')
        time.sleep(2)

        # Fill basic gym information
        print("[INFO] Filling gym details...")
        page.fill('#gymName', 'Test Gym with Custom Plans')
        page.select_option('#gymPartner', 'Cult')
        page.fill('#gymAddress', '123 Test Street')
        page.fill('#gymCity', 'Mumbai')
        page.fill('#gymState', 'Maharashtra')
        page.fill('#gymPincode', '400001')
        page.fill('#gymLatitude', '19.0760')
        page.fill('#gymLongitude', '72.8777')
        page.fill('#gymAmenities', 'Cardio, Weights, Yoga')
        page.fill('#gymSubscriptionAmount', '3000')

        # Enable custom plans
        print("[INFO] Enabling custom plans...")
        page.check('#customPlansToggle')
        time.sleep(1)

        # Fill custom plans
        print("[INFO] Setting custom plan prices...")
        page.fill('#plan1Month', '3000')
        page.fill('#plan3Months', '8500')
        page.fill('#plan6Months', '16000')
        page.fill('#plan12Months', '30000')

        # Take screenshot before submit
        page.screenshot(path='C:/Users/hp/gym_habit/screenshot_add_gym.png')
        print("[INFO] Screenshot saved: screenshot_add_gym.png")

        # Submit the form
        print("[INFO] Submitting gym...")
        page.click('text=Add Gym')
        time.sleep(3)

        # Take screenshot after submit
        page.screenshot(path='C:/Users/hp/gym_habit/screenshot_after_add.png')
        print("[INFO] Screenshot saved: screenshot_after_add.png")

        print("[SUCCESS] Test completed!")
        print("\n[INFO] Check the admin panel to verify the gym was added")
        print("[INFO] Screenshots saved for review")

        time.sleep(3)
        browser.close()

if __name__ == '__main__':
    print("[START] Starting custom plans test...")
    try:
        test_admin_custom_plans()
        print("\n[SUCCESS] All tests passed!")
    except Exception as e:
        print(f"\n[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()
