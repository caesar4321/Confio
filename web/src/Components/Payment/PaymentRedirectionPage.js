import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import FriendlyHeroSection from '../LandingPage/FriendlyHeroSection';

const PaymentRedirectionPage = () => {
    const { id } = useParams();
    const [redirecting, setRedirecting] = useState(true);

    useEffect(() => {
        // Attempt deep link redirection
        if (id) {
            const appLink = `confio://pay/${id}`;
            const fallbackLink = 'https://apps.apple.com/us/app/conf%C3%ADo/id6476486307'; // Update with actual generic store link or landing

            // Try to open the app
            window.location.href = appLink;

            // Fallback logic could be added here (e.g. check if user stays on page)
            // For now, we just show the landing page content as fallback/background

            const timer = setTimeout(() => {
                setRedirecting(false);
            }, 2000);
            return () => clearTimeout(timer);
        }
    }, [id]);

    return (
        <div className="payment-redirection-page">
            <FriendlyHeroSection
                title="Complete your payment in the Confío App"
                subtitle="If the app didn't open automatically, use the buttons below."
                showDownloadButtons={true}
            />
            {/* We reuse the Hero Section as it already has download buttons and nice styling */}
        </div>
    );
};

export default PaymentRedirectionPage;
