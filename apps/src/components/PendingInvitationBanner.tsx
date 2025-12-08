import React from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Alert,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useQuery, useMutation } from '@apollo/client';
import { GET_MY_INVITATIONS, ACCEPT_INVITATION } from '../apollo/queries';
import { useAccount } from '../contexts/AccountContext';

export const PendingInvitationBanner = () => {
  const { data, loading, refetch } = useQuery(GET_MY_INVITATIONS, {
    fetchPolicy: 'cache-and-network',
  });

  const [acceptInvitation] = useMutation(ACCEPT_INVITATION);
  const { refreshAccounts } = useAccount();

  const invitations = data?.myInvitations || [];

  if (loading || invitations.length === 0) {
    return null;
  }

  const handleAccept = async (invitation: any) => {
    try {
      const { data } = await acceptInvitation({
        variables: {
          invitationCode: invitation.invitationCode,
        },
      });

      if (data?.acceptInvitation?.success) {
        Alert.alert(
          '¡Éxito!',
          `Ahora eres empleado de ${invitation.business.name}`,
          [
            {
              text: 'OK',
              onPress: async () => {
                await refreshAccounts();
                await refetch();
              },
            },
          ]
        );
      } else {
        Alert.alert(
          'Error',
          data?.acceptInvitation?.errors?.[0] || 'No se pudo aceptar la invitación',
          [{ text: 'OK' }]
        );
      }
    } catch (error) {
      Alert.alert('Error', 'Ocurrió un error al aceptar la invitación', [{ text: 'OK' }]);
    }
  };

  const getRoleLabel = (role: string) => {
    const roleLabels: { [key: string]: string } = {
      cashier: 'Cajero',
      manager: 'Gerente',
      admin: 'Administrador',
    };
    return roleLabels[role] || role;
  };

  // Show only the first invitation as a banner
  const invitation = invitations[0];

  return (
    <View style={styles.container}>
      <View style={styles.iconContainer}>
        <Icon name="mail" size={20} color="#fff" />
      </View>

      <View style={styles.content}>
        <Text style={styles.title}>Invitación pendiente</Text>
        <Text style={styles.subtitle}>
          {invitation.business.name} te invita como {getRoleLabel(invitation.role)}
        </Text>
        {invitation.message && (
          <Text style={styles.message} numberOfLines={2}>
            "{invitation.message}"
          </Text>
        )}
      </View>

      <View style={styles.actions}>
        <TouchableOpacity
          style={styles.acceptButton}
          onPress={() => handleAccept(invitation)}
        >
          <Icon name="check" size={16} color="#fff" />
        </TouchableOpacity>

        {invitations.length > 1 && (
          <View style={styles.badge}>
            <Text style={styles.badgeText}>+{invitations.length - 1}</Text>
          </View>
        )}
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#7c3aed',
    marginHorizontal: 16,
    marginTop: 16,
    padding: 16,
    borderRadius: 16,
    shadowColor: '#000',
    shadowOffset: {
      width: 0,
      height: 2,
    },
    shadowOpacity: 0.1,
    shadowRadius: 3,
    elevation: 3,
  },
  iconContainer: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: 'rgba(255, 255, 255, 0.2)',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  content: {
    flex: 1,
  },
  title: {
    fontSize: 14,
    fontWeight: '600',
    color: '#fff',
    marginBottom: 2,
  },
  subtitle: {
    fontSize: 13,
    color: 'rgba(255, 255, 255, 0.9)',
    marginBottom: 4,
  },
  message: {
    fontSize: 12,
    color: 'rgba(255, 255, 255, 0.8)',
    fontStyle: 'italic',
  },
  actions: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  acceptButton: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: '#10b981',
    alignItems: 'center',
    justifyContent: 'center',
  },
  badge: {
    backgroundColor: 'rgba(255, 255, 255, 0.2)',
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 12,
  },
  badgeText: {
    fontSize: 11,
    fontWeight: '600',
    color: '#fff',
  },
});