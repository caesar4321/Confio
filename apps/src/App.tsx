import React from 'react';
import { SafeAreaView, StyleSheet } from 'react-native';
import { ApolloProvider } from '@apollo/client';
import { client } from './apollo/client';
import { ZkLoginManager } from './components/ZkLoginManager';

const App: React.FC = () => {
  return (
    <ApolloProvider client={client}>
      <SafeAreaView style={styles.container}>
        <ZkLoginManager />
      </SafeAreaView>
    </ApolloProvider>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#fff',
  },
});

export default App; 