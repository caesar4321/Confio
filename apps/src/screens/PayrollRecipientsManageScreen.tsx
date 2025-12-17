import React, { useMemo, useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, SafeAreaView, FlatList, RefreshControl, Platform, StatusBar } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import { useQuery } from '@apollo/client';
import { GET_PAYROLL_RECIPIENTS } from '../apollo/queries';
import PayrollRecipientModal from '../components/PayrollRecipientModal';

type NavigationProp = NativeStackNavigationProp<MainStackParamList>;

const colors = {
  primary: '#34d399',
  text: '#111827',
  muted: '#6b7280',
  border: '#e5e7eb',
  bg: '#f9fafb',
};

export const PayrollRecipientsManageScreen = () => {
  const navigation = useNavigation<NavigationProp>();
  const [showAddModal, setShowAddModal] = useState(false);
  const { data, loading, refetch } = useQuery(GET_PAYROLL_RECIPIENTS, {
    fetchPolicy: 'cache-and-network',
  });

  const recipients = useMemo(() => data?.payrollRecipients || [], [data]);

  const handleRecipientPress = (recipient: any) => {
    navigation.navigate('PayeeDetail', {
      recipientId: recipient.id,
      displayName: recipient.displayName || recipient.recipientUser?.firstName || recipient.recipientUser?.username || 'Destinatario',
      username: recipient.recipientUser?.username,
      accountId: recipient.recipientAccount?.id || '',
      employeeRole: recipient.employeeRole,
      employeePermissions: recipient.employeeEffectivePermissions,
      onDeleted: () => refetch(),
    } as any);
  };

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
          <Icon name="chevron-left" size={24} color={colors.text} />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Destinatarios</Text>
        <TouchableOpacity onPress={() => setShowAddModal(true)} style={styles.addButton}>
          <Icon name="plus" size={20} color={colors.primary} />
        </TouchableOpacity>
      </View>

      <View style={styles.infoCard}>
        <Icon name="info" size={16} color={colors.muted} />
        <Text style={styles.infoText}>
          Los destinatarios son personas que recibirán pagos de nómina. Toca uno para configurar montos y programar pagos.
        </Text>
      </View>

      <FlatList
        data={recipients}
        keyExtractor={(item: any) => item.id}
        refreshControl={
          <RefreshControl
            refreshing={loading}
            onRefresh={refetch}
            tintColor={colors.primary}
          />
        }
        ListEmptyComponent={
          <View style={styles.emptyState}>
            <Icon name="users" size={48} color={colors.muted} />
            <Text style={styles.emptyTitle}>Sin destinatarios</Text>
            <Text style={styles.emptySubtitle}>
              Agrega personas que recibirán pagos de nómina
            </Text>
            <TouchableOpacity
              style={styles.emptyButton}
              onPress={() => setShowAddModal(true)}
            >
              <Icon name="plus" size={18} color="#fff" />
              <Text style={styles.emptyButtonText}>Agregar destinatario</Text>
            </TouchableOpacity>
          </View>
        }
        renderItem={({ item }) => {
          const title = item.displayName || item.recipientUser?.firstName || item.recipientUser?.username || 'Destinatario';
          const subtitle = item.recipientUser?.username ? `@${item.recipientUser.username}` : '';
          const isEmployee = !!item.isEmployee;

          return (
            <TouchableOpacity
              style={styles.recipientCard}
              onPress={() => handleRecipientPress(item)}
              activeOpacity={0.7}
            >
              <View style={styles.recipientAvatar}>
                <Text style={styles.recipientAvatarText}>{title.charAt(0).toUpperCase()}</Text>
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.recipientName}>{title}</Text>
                {subtitle ? <Text style={styles.recipientSubtext}>{subtitle}</Text> : null}
                <View style={styles.badgeRow}>
                  <View style={[styles.badge, isEmployee ? styles.badgeGreen : styles.badgeGray]}>
                    <Text style={[styles.badgeText, isEmployee ? styles.badgeTextGreen : styles.badgeTextGray]}>
                      {isEmployee ? 'Empleado' : 'Externo'}
                    </Text>
                  </View>
                </View>
              </View>
              <Icon name="chevron-right" size={20} color={colors.muted} />
            </TouchableOpacity>
          );
        }}
        contentContainerStyle={styles.listContent}
        ListFooterComponent={
          recipients.length > 0 ? (
            <TouchableOpacity
              style={styles.footerAddButton}
              onPress={() => setShowAddModal(true)}
            >
              <Icon name="plus" size={18} color={colors.primary} />
              <Text style={styles.footerAddButtonText}>Agregar destinatario</Text>
            </TouchableOpacity>
          ) : null
        }
      />

      <PayrollRecipientModal
        visible={showAddModal}
        onClose={() => setShowAddModal(false)}
        onChanged={() => {
          setShowAddModal(false);
          refetch();
        }}
      />
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff' },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
    marginTop: Platform.OS === 'android' ? (StatusBar.currentHeight || 24) + 10 : 0,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  backButton: {
    width: 32,
    height: 32,
    alignItems: 'center',
    justifyContent: 'center',
  },
  headerTitle: {
    flex: 1,
    textAlign: 'center',
    fontSize: 18,
    color: colors.text,
    fontWeight: '600',
  },
  addButton: {
    width: 32,
    height: 32,
    alignItems: 'center',
    justifyContent: 'center',
  },
  infoCard: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
    margin: 16,
    padding: 12,
    backgroundColor: colors.bg,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
  },
  infoText: {
    flex: 1,
    fontSize: 13,
    color: colors.muted,
    lineHeight: 18,
  },
  listContent: {
    padding: 16,
  },
  recipientCard: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#fff',
    paddingVertical: 12,
    paddingHorizontal: 12,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: 10,
    shadowColor: '#000',
    shadowOpacity: 0.03,
    shadowRadius: 6,
    shadowOffset: { width: 0, height: 2 },
    gap: 12,
  },
  recipientAvatar: {
    width: 44,
    height: 44,
    borderRadius: 12,
    backgroundColor: '#ecfdf3',
    alignItems: 'center',
    justifyContent: 'center',
  },
  recipientAvatarText: {
    fontSize: 18,
    fontWeight: '700',
    color: '#065f46',
  },
  recipientName: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.text,
  },
  recipientSubtext: {
    fontSize: 13,
    color: colors.muted,
    marginTop: 2,
  },
  badgeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginTop: 6,
  },
  badge: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 6,
  },
  badgeText: {
    fontSize: 11,
    fontWeight: '700',
  },
  badgeGreen: { backgroundColor: '#ecfdf3' },
  badgeTextGreen: { color: '#065f46' },
  badgeGray: { backgroundColor: '#f3f4f6' },
  badgeTextGray: { color: '#6b7280' },
  emptyState: {
    alignItems: 'center',
    paddingVertical: 60,
    paddingHorizontal: 32,
  },
  emptyTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.text,
    marginTop: 16,
  },
  emptySubtitle: {
    fontSize: 14,
    color: colors.muted,
    textAlign: 'center',
    marginTop: 8,
    marginBottom: 24,
  },
  emptyButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.primary,
    paddingVertical: 12,
    paddingHorizontal: 20,
    borderRadius: 12,
    gap: 8,
  },
  emptyButtonText: {
    fontSize: 15,
    fontWeight: '700',
    color: '#fff',
  },
  footerAddButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 14,
    marginTop: 8,
    borderWidth: 1,
    borderColor: '#e5e7eb',
    borderRadius: 12,
    backgroundColor: '#fff',
    gap: 8,
    borderStyle: 'dashed',
  },
  footerAddButtonText: {
    fontSize: 15,
    fontWeight: '600',
    color: colors.primary,
  },
});

export default PayrollRecipientsManageScreen;
