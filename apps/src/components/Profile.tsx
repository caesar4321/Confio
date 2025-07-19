import React from 'react';
import { View, Text, ActivityIndicator } from 'react-native';
import { useAuth } from '../contexts/AuthContext';
import { useAccountManager } from '../hooks/useAccountManager';

const Profile: React.FC = () => {
  const { profileData, isProfileLoading } = useAuth();
  const { activeAccount } = useAccountManager();

  if (isProfileLoading) return <ActivityIndicator size="large" />;
  if (!profileData) return <Text>No profile data available</Text>;

  const isBusinessMode = activeAccount?.type === 'business';
  const userProfile = profileData.userProfile;
  const businessProfile = profileData.businessProfile;

  return (
    <View style={{ padding: 20 }}>
      <Text style={{ fontSize: 24, marginBottom: 20 }}>
        {isBusinessMode ? 'Business Profile' : 'User Profile'}
      </Text>
      
      {isBusinessMode && businessProfile ? (
        // Business Profile Display
        <View>
          <Text style={{ fontSize: 18, fontWeight: 'bold', marginBottom: 10 }}>
            {businessProfile.name}
          </Text>
          <Text>Business ID: {businessProfile.id}</Text>
          <Text>Category: {businessProfile.category}</Text>
          {businessProfile.description && (
            <Text>Description: {businessProfile.description}</Text>
          )}
          {businessProfile.address && (
            <Text>Address: {businessProfile.address}</Text>
          )}
          {businessProfile.businessRegistrationNumber && (
            <Text>Registration Number: {businessProfile.businessRegistrationNumber}</Text>
          )}
          {businessProfile.createdAt && (
            <Text>Created: {new Date(businessProfile.createdAt).toLocaleDateString()}</Text>
          )}
        </View>
      ) : userProfile ? (
        // User Profile Display
        <View>
          <Text style={{ fontSize: 18, fontWeight: 'bold', marginBottom: 10 }}>
            {userProfile.firstName && userProfile.lastName 
              ? `${userProfile.firstName} ${userProfile.lastName}`
              : userProfile.username
            }
          </Text>
          <Text>User ID: {userProfile.id}</Text>
          <Text>Email: {userProfile.email}</Text>
          <Text>Username: {userProfile.username}</Text>
          {userProfile.firstName && (
            <Text>First Name: {userProfile.firstName}</Text>
          )}
          {userProfile.lastName && (
            <Text>Last Name: {userProfile.lastName}</Text>
          )}
          {userProfile.phoneCountry && (
            <Text>Phone Country: {userProfile.phoneCountry}</Text>
          )}
          {userProfile.phoneNumber && (
            <Text>Phone Number: {userProfile.phoneNumber}</Text>
          )}
          <Text>Identity Verified: {userProfile.isIdentityVerified ? 'Yes' : 'No'}</Text>
          {userProfile.verificationStatus && (
            <Text>Verification Status: {userProfile.verificationStatus}</Text>
          )}
          {userProfile.lastVerifiedDate && (
            <Text>Last Verified: {new Date(userProfile.lastVerifiedDate).toLocaleDateString()}</Text>
          )}
        </View>
      ) : (
        <Text>No profile data available for current account type</Text>
      )}
    </View>
  );
};

export default Profile; 