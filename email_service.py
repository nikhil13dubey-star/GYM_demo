"""
SendGrid Email Service for Gym Habit
Handles all email notifications - auto and manual triggers
"""

import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, To, Cc, Content, HtmlContent
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

# Configuration
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
FROM_EMAIL = os.getenv("SENDGRID_FROM_EMAIL", "noreply.healthcare@example.com")
FROM_NAME = os.getenv("SENDGRID_FROM_NAME", "Demo Webapp")
SUPPORT_PHONE = "+91-99999-00000"

# Internal recipients CC'd on every PAYMENT_CONFIRMATION email so they have
# visibility on payments and can reply if needed.
PAYMENT_CONFIRMATION_CC = [
    "ops.one@example.com",
    "ops.two@example.com",
]


class EmailService:
    """SendGrid email service for Gym Habit notifications"""

    def __init__(self):
        self.client = SendGridAPIClient(SENDGRID_API_KEY) if SENDGRID_API_KEY else None
        self.from_email = Email(FROM_EMAIL, FROM_NAME)

    def _get_base_template(self, content: str) -> str:
        """Base HTML email template"""
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Demo Webapp</title>
        </head>
        <body style="margin: 0; padding: 0; font-family: 'Segoe UI', Arial, sans-serif; background-color: #f5f5f5;">
            <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f5f5f5; padding: 40px 20px;">
                <tr>
                    <td align="center">
                        <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 16px; box-shadow: 0 4px 24px rgba(0,0,0,0.1);">
                            <!-- Header -->
                            <tr>
                                <td style="background: linear-gradient(135deg, #0c53a0 0%, #0a4485 100%); padding: 32px; border-radius: 16px 16px 0 0; text-align: center;">
                                    <h1 style="margin: 0; color: #ffffff; font-size: 28px; font-weight: 700;">Demo Webapp</h1>
                                    
                                </td>
                            </tr>
                            <!-- Content -->
                            <tr>
                                <td style="padding: 40px 32px;">
                                    {content}
                                </td>
                            </tr>
                            <!-- Footer -->
                            <tr>
                                <td style="background-color: #f8f9fa; padding: 24px 32px; border-radius: 0 0 16px 16px; text-align: center;">
                                    <p style="margin: 0 0 8px 0; color: #6b7280; font-size: 14px;">
                                        Need help? Contact us at <a href="tel:{SUPPORT_PHONE}" style="color: #0c53a0;">{SUPPORT_PHONE}</a>
                                    </p>
                                    <p style="margin: 0; color: #9ca3af; font-size: 12px;">
                                        &copy; {datetime.now().year} Demo webapp. All rights reserved.
                                    </p>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """

    def _send_email(self, to_email: str, subject: str, html_content: str, cc: list = None) -> dict:
        """
        Send email via SendGrid. Optional `cc` is a list of CC addresses.
        Every return path includes the envelope (from/to/cc/subject) so callers
        can log exactly what was (attempted to be) sent.
        """
        # CC actually applied (skip any that equal the To address to avoid dupes)
        cc_applied = [
            addr.strip() for addr in (cc or [])
            if addr and addr.strip().lower() != (to_email or "").strip().lower()
        ]
        envelope = {"from": FROM_EMAIL, "to": to_email, "cc": cc_applied, "subject": subject}

        if not self.client:
            return {"success": False, "error": "Email sending is disabled in this demo (no SENDGRID_API_KEY set)", **envelope}

        try:
            message = Mail(
                from_email=self.from_email,
                to_emails=To(to_email),
                subject=subject,
                html_content=HtmlContent(html_content)
            )
            for addr in cc_applied:
                message.add_cc(Cc(addr))
            response = self.client.send(message)
            return {
                "success": True,
                "status_code": response.status_code,
                "message": f"Email sent to {to_email}" + (f" (cc: {', '.join(cc_applied)})" if cc_applied else ""),
                **envelope
            }
        except Exception as e:
            return {"success": False, "error": str(e), **envelope}

    # =========================================================================
    # EMAIL TEMPLATES
    # =========================================================================

    def build_lead_acknowledgement(self, customer_name: str, gym_name: str) -> tuple:
        """
        LEAD_ACKNOWLEDGEMENT - Auto-triggered on lead submission
        Returns (subject, html).
        """
        subject = "Thank You for Your Interest - Demo Webapp Gym Package"

        content = f"""
        <h2 style="margin: 0 0 24px 0; color: #111827; font-size: 24px;">Hello {customer_name}!</h2>

        <p style="margin: 0 0 16px 0; color: #374151; font-size: 16px; line-height: 1.6;">
            Thank you for your interest in our <strong>Gym Package</strong> at <strong>{gym_name}</strong>.
        </p>

        <p style="margin: 0 0 24px 0; color: #374151; font-size: 16px; line-height: 1.6;">
            Our wellness team will contact you shortly to help you start your fitness journey.
        </p>

        <div style="background: linear-gradient(135deg, #10B981 0%, #059669 100%); border-radius: 12px; padding: 24px; text-align: center; margin: 24px 0;">
            <p style="margin: 0; color: #ffffff; font-size: 18px; font-weight: 600;">
                We'll reach out within 24 hours!
            </p>
        </div>

        <p style="margin: 24px 0 0 0; color: #6b7280; font-size: 14px;">
            If you have any questions, feel free to call us at <strong>{SUPPORT_PHONE}</strong>.
        </p>
        """

        return subject, self._get_base_template(content)

    def send_lead_acknowledgement(self, customer_email: str, customer_name: str, gym_name: str, cc: list = None) -> dict:
        subject, html = self.build_lead_acknowledgement(customer_name, gym_name)
        return self._send_email(customer_email, subject, html, cc=cc)

    def build_no_response_followup(self, customer_name: str, gym_name: str) -> tuple:
        """
        NO_RESPONSE_FOLLOWUP - Manual trigger when customer doesn't answer call
        Returns (subject, html).
        """
        subject = "We Tried Reaching You - Demo Webapp"

        content = f"""
        <h2 style="margin: 0 0 24px 0; color: #111827; font-size: 24px;">Hi {customer_name},</h2>

        <p style="margin: 0 0 16px 0; color: #374151; font-size: 16px; line-height: 1.6;">
            We tried reaching you regarding your <strong>Gym Package</strong> inquiry for <strong>{gym_name}</strong>, but couldn't connect.
        </p>

        <div style="background-color: #FEF3C7; border-left: 4px solid #F59E0B; padding: 16px 20px; margin: 24px 0; border-radius: 0 8px 8px 0;">
            <p style="margin: 0; color: #92400E; font-size: 15px;">
                <strong>Please call us back</strong> or reply to this email so we can assist you.
            </p>
        </div>

        <div style="text-align: center; margin: 32px 0;">
            <a href="tel:{SUPPORT_PHONE}" style="display: inline-block; background: linear-gradient(135deg, #0c53a0 0%, #0a4485 100%); color: #ffffff; text-decoration: none; padding: 16px 32px; border-radius: 8px; font-size: 16px; font-weight: 600;">
                Call Us: {SUPPORT_PHONE}
            </a>
        </div>

        <p style="margin: 24px 0 0 0; color: #6b7280; font-size: 14px;">
            We're here to help you achieve your fitness goals!
        </p>
        """

        return subject, self._get_base_template(content)

    def send_no_response_followup(self, customer_email: str, customer_name: str, gym_name: str, cc: list = None) -> dict:
        subject, html = self.build_no_response_followup(customer_name, gym_name)
        return self._send_email(customer_email, subject, html, cc=cc)

    def build_payment_confirmation(self, customer_name: str, gym_name: str, amount: float,
                                   transaction_id: str, plan_name: str = "Gym Package") -> tuple:
        """
        PAYMENT_CONFIRMATION - Manual trigger after payment validation
        Returns (subject, html).
        """
        subject = "Payment Received - Demo Webapp Gym Package"

        content = f"""
        <h2 style="margin: 0 0 24px 0; color: #111827; font-size: 24px;">Payment Confirmed!</h2>

        <p style="margin: 0 0 16px 0; color: #374151; font-size: 16px; line-height: 1.6;">
            Hi <strong>{customer_name}</strong>, we have successfully received your payment.
        </p>

        <div style="background-color: #F0FDF4; border: 1px solid #BBF7D0; border-radius: 12px; padding: 24px; margin: 24px 0;">
            <h3 style="margin: 0 0 16px 0; color: #166534; font-size: 18px;">Transaction Details</h3>
            <table style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td style="padding: 8px 0; color: #6b7280; font-size: 14px;">Transaction ID</td>
                    <td style="padding: 8px 0; color: #111827; font-size: 14px; text-align: right; font-weight: 600;">{transaction_id}</td>
                </tr>
                <tr>
                    <td style="padding: 8px 0; color: #6b7280; font-size: 14px;">Gym</td>
                    <td style="padding: 8px 0; color: #111827; font-size: 14px; text-align: right; font-weight: 600;">{gym_name}</td>
                </tr>
                <tr>
                    <td style="padding: 8px 0; color: #6b7280; font-size: 14px;">Plan</td>
                    <td style="padding: 8px 0; color: #111827; font-size: 14px; text-align: right; font-weight: 600;">{plan_name}</td>
                </tr>
                <tr style="border-top: 1px solid #BBF7D0;">
                    <td style="padding: 16px 0 8px 0; color: #166534; font-size: 16px; font-weight: 700;">Amount Paid</td>
                    <td style="padding: 16px 0 8px 0; color: #166534; font-size: 20px; text-align: right; font-weight: 700;">Rs. {amount:,.2f}</td>
                </tr>
            </table>
        </div>

        <div style="background: linear-gradient(135deg, #10B981 0%, #059669 100%); border-radius: 12px; padding: 24px; text-align: center;">
            <p style="margin: 0; color: #ffffff; font-size: 18px; font-weight: 600;">
                Welcome to your fitness journey!
            </p>
        </div>

        <p style="margin: 24px 0 0 0; color: #6b7280; font-size: 14px;">
            Your membership details will be shared with you shortly. For any queries, contact us at <strong>{SUPPORT_PHONE}</strong>.
        </p>
        """

        return subject, self._get_base_template(content)

    def send_payment_confirmation(self, customer_email: str, customer_name: str,
                                   gym_name: str, amount: float, transaction_id: str,
                                   plan_name: str = "Gym Package", cc: list = None) -> dict:
        subject, html = self.build_payment_confirmation(customer_name, gym_name, amount, transaction_id, plan_name)
        # CC internal stakeholders so they have payment visibility and can reply.
        # `cc=None` falls back to the built-in default; callers pass the DB-managed list.
        return self._send_email(customer_email, subject, html,
                                cc=PAYMENT_CONFIRMATION_CC if cc is None else cc)

    def build_interim_info(self, customer_name: str, reference_id: str,
                           transaction_amount, plan_name: str) -> tuple:
        """
        INTERIM_INFO - Manual trigger after payment is marked 'paid'.
        Sends transaction details to the customer while the final tax invoice is being prepared.
        Returns (subject, html).
        """
        subject = "Your Gym Subscription Confirmation - Demo Webapp"

        # Format amount safely (could be int, float, or None)
        try:
            amount_display = f"Rs. {float(transaction_amount):,.2f}" if transaction_amount not in (None, "") else "N/A"
        except (TypeError, ValueError):
            amount_display = str(transaction_amount)

        content = f"""
        <h2 style="margin: 0 0 24px 0; color: #111827; font-size: 24px;">Hi {customer_name},</h2>

        <p style="margin: 0 0 16px 0; color: #374151; font-size: 16px; line-height: 1.6;">
            Your gym subscription has successfully processed. Please find the transaction details below:
        </p>

        <div style="background-color: #F0FDF4; border: 1px solid #BBF7D0; border-radius: 12px; padding: 24px; margin: 24px 0;">
            <table style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td style="padding: 8px 0; color: #6b7280; font-size: 14px;">Name</td>
                    <td style="padding: 8px 0; color: #111827; font-size: 14px; text-align: right; font-weight: 600;">{customer_name}</td>
                </tr>
                <tr>
                    <td style="padding: 8px 0; color: #6b7280; font-size: 14px;">Transaction Number</td>
                    <td style="padding: 8px 0; color: #111827; font-size: 14px; text-align: right; font-weight: 600;">{reference_id}</td>
                </tr>
                <tr>
                    <td style="padding: 8px 0; color: #6b7280; font-size: 14px;">Transaction Amount</td>
                    <td style="padding: 8px 0; color: #111827; font-size: 14px; text-align: right; font-weight: 600;">{amount_display}</td>
                </tr>
                <tr>
                    <td style="padding: 8px 0; color: #6b7280; font-size: 14px;">Subscription Type</td>
                    <td style="padding: 8px 0; color: #111827; font-size: 14px; text-align: right; font-weight: 600;">{plan_name}</td>
                </tr>
            </table>
        </div>

        <p style="margin: 24px 0 16px 0; color: #374151; font-size: 15px; line-height: 1.6;">
            If you have any questions or need further assistance please feel free to reach out at:<br>
            <strong>{SUPPORT_PHONE}</strong> | <a href="mailto:customerexperience@example.com" style="color: #0c53a0;">customerexperience@example.com</a>
        </p>

        <div style="background-color: #FEF3C7; border-left: 4px solid #F59E0B; padding: 16px 20px; margin: 24px 0; border-radius: 0 8px 8px 0;">
            <p style="margin: 0; color: #92400E; font-size: 14px;">
                <strong>Please note:</strong> The final tax invoice will be shared with you in 7-10 working days.
            </p>
        </div>

        <p style="margin: 32px 0 0 0; color: #374151; font-size: 15px;">
            Best Regards,<br>
            <strong>Team Demo Webapp</strong>
        </p>
        """

        return subject, self._get_base_template(content)

    def send_interim_info(self, customer_email: str, customer_name: str,
                          reference_id: str, transaction_amount, plan_name: str, cc: list = None) -> dict:
        subject, html = self.build_interim_info(customer_name, reference_id, transaction_amount, plan_name)
        return self._send_email(customer_email, subject, html, cc=cc)

    def build_no_interest_closure(self, customer_name: str, gym_name: str) -> tuple:
        """
        NO_INTEREST_CLOSURE - Manual trigger to close inactive leads
        Returns (subject, html).
        """
        subject = "Your Gym Package Request - Demo Webapp"

        content = f"""
        <h2 style="margin: 0 0 24px 0; color: #111827; font-size: 24px;">Hi {customer_name},</h2>

        <p style="margin: 0 0 16px 0; color: #374151; font-size: 16px; line-height: 1.6;">
            We made multiple attempts to reach you regarding your <strong>Gym Package</strong> inquiry for <strong>{gym_name}</strong>.
        </p>

        <p style="margin: 0 0 24px 0; color: #374151; font-size: 16px; line-height: 1.6;">
            As we haven't heard back from you, this request is now <strong>closed</strong>.
        </p>

        <div style="background-color: #F3F4F6; border-radius: 12px; padding: 24px; text-align: center; margin: 24px 0;">
            <p style="margin: 0 0 16px 0; color: #374151; font-size: 16px;">
                Still interested in starting your fitness journey?
            </p>
            <a href="mailto:{FROM_EMAIL}?subject=Reopen%20Gym%20Package%20Request" style="display: inline-block; background: linear-gradient(135deg, #0c53a0 0%, #0a4485 100%); color: #ffffff; text-decoration: none; padding: 14px 28px; border-radius: 8px; font-size: 15px; font-weight: 600;">
                Get In Touch
            </a>
        </div>

        <p style="margin: 24px 0 0 0; color: #6b7280; font-size: 14px;">
            Feel free to reach out whenever you're ready. We're here to help!
        </p>
        """

        return subject, self._get_base_template(content)

    def send_no_interest_closure(self, customer_email: str, customer_name: str, gym_name: str, cc: list = None) -> dict:
        subject, html = self.build_no_interest_closure(customer_name, gym_name)
        return self._send_email(customer_email, subject, html, cc=cc)


# Singleton instance
email_service = EmailService()
