import 'package:flutter/material.dart';

import '../app_state.dart';
import '../models.dart';

/// Shared feed of all agent messages (newest first) plus a sheet to send a message.
class ChatScreen extends StatelessWidget {
  const ChatScreen({super.key, required this.state});

  final AppState state;

  void _openComposer(BuildContext context) {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (ctx) => Padding(
        padding: EdgeInsets.only(bottom: MediaQuery.of(ctx).viewInsets.bottom),
        child: MessageComposer(state: state),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final messages = state.feed.reversed.toList();
    final filter = state.conversationFilter;
    return Scaffold(
      backgroundColor: Colors.transparent,
      floatingActionButton: FloatingActionButton.extended(
        heroTag: 'chat-fab',
        onPressed: state.me == null ? null : () => _openComposer(context),
        icon: const Icon(Icons.send),
        label: const Text('Mesaj yaz'),
      ),
      body: Column(
        children: [
          if (filter != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
              child: Align(
                alignment: Alignment.centerLeft,
                child: InputChip(
                  label: Text('Konuşma #${filter.length > 8 ? filter.substring(0, 8) : filter}'),
                  onDeleted: () => state.setConversationFilter(null),
                ),
              ),
            ),
          Expanded(
            child: RefreshIndicator(
              onRefresh: state.refresh,
              child: messages.isEmpty
                  ? ListView(
                      physics: const AlwaysScrollableScrollPhysics(),
                      children: [
                        Padding(
                          padding: const EdgeInsets.symmetric(vertical: 48),
                          child: Center(
                            child: Text(
                              state.firstLoadDone
                                  ? (state.error ?? 'Henüz mesaj yok.')
                                  : 'Yükleniyor…',
                              textAlign: TextAlign.center,
                            ),
                          ),
                        ),
                      ],
                    )
                  : ListView.builder(
                      physics: const AlwaysScrollableScrollPhysics(),
                      padding: const EdgeInsets.fromLTRB(12, 8, 12, 88),
                      itemCount: messages.length,
                      itemBuilder: (context, i) => MessageCard(
                        message: messages[i],
                        isMine: messages[i].sender == state.me,
                        onFilter: () => state.setConversationFilter(messages[i].conversationId),
                      ),
                    ),
            ),
          ),
        ],
      ),
    );
  }
}

class MessageCard extends StatelessWidget {
  const MessageCard({
    super.key,
    required this.message,
    required this.isMine,
    required this.onFilter,
  });

  final FeedMessage message;
  final bool isMine;
  final VoidCallback onFilter;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final loud = message.priority == 'HIGH' || message.priority == 'CRITICAL';
    return Card(
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(
          color: message.isAlert
              ? scheme.error
              : (isMine ? scheme.primary : scheme.outlineVariant),
        ),
      ),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onLongPress: message.conversationId.isEmpty ? null : onFilter,
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Wrap(
                spacing: 6,
                runSpacing: 2,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  Text(
                    '${message.sender} → ${message.receiver}',
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                  Text(message.type, style: Theme.of(context).textTheme.labelSmall),
                  if (message.priority != 'NORMAL')
                    Text(
                      message.priority,
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w600,
                        color: loud ? scheme.error : scheme.outline,
                      ),
                    ),
                  if (message.responseRequired && message.status != 'ANSWERED')
                    Text('yanıt gerekli', style: TextStyle(fontSize: 11, color: Colors.orange.shade800)),
                  if (message.taskId != null)
                    Text(message.taskId!, style: Theme.of(context).textTheme.labelSmall),
                  Text(shortTime(message.timestamp), style: Theme.of(context).textTheme.labelSmall),
                ],
              ),
              const SizedBox(height: 4),
              Text(message.subject, style: const TextStyle(fontWeight: FontWeight.w600)),
              if (message.content.isNotEmpty) ...[
                const SizedBox(height: 2),
                Text(message.content),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class MessageComposer extends StatefulWidget {
  const MessageComposer({super.key, required this.state});

  final AppState state;

  @override
  State<MessageComposer> createState() => _MessageComposerState();
}

class _MessageComposerState extends State<MessageComposer> {
  final _subject = TextEditingController();
  final _content = TextEditingController();
  String _receiver = 'claude1';
  String _type = 'STATUS_UPDATE';
  String _priority = 'NORMAL';
  bool _responseRequired = false;
  bool _sending = false;
  String? _error;

  @override
  void dispose() {
    _subject.dispose();
    _content.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final subject = _subject.text.trim();
    if (subject.isEmpty) {
      setState(() => _error = 'Konu gerekli');
      return;
    }
    setState(() {
      _sending = true;
      _error = null;
    });
    final err = await widget.state.sendMessage(
      receiver: _receiver,
      messageType: _type,
      subject: subject,
      content: _content.text,
      priority: _priority,
      responseRequired: _responseRequired,
    );
    if (!mounted) return;
    if (err == null) {
      Navigator.of(context).pop();
    } else {
      setState(() {
        _sending = false;
        _error = err;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final conversation = widget.state.conversationFilter;
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text('Mesaj gönder', style: Theme.of(context).textTheme.titleMedium),
          if (conversation != null)
            Text(
              'Seçili konuşmaya eklenecek.',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          const SizedBox(height: 8),
          _Dropdown(
            label: 'Alıcı',
            value: _receiver,
            items: const [...agentIds, broadcastId],
            onChanged: (v) => setState(() => _receiver = v),
          ),
          const SizedBox(height: 8),
          _Dropdown(
            label: 'Tür',
            value: _type,
            items: messageTypes,
            onChanged: (v) => setState(() => _type = v),
          ),
          const SizedBox(height: 8),
          _Dropdown(
            label: 'Öncelik',
            value: _priority,
            items: priorities,
            onChanged: (v) => setState(() => _priority = v),
          ),
          const SizedBox(height: 8),
          TextField(
            controller: _subject,
            maxLength: 200,
            decoration: const InputDecoration(labelText: 'Konu', border: OutlineInputBorder()),
          ),
          TextField(
            controller: _content,
            maxLines: 4,
            maxLength: 20000,
            decoration: const InputDecoration(labelText: 'İçerik', border: OutlineInputBorder()),
          ),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('Yanıt gerekli'),
            value: _responseRequired,
            onChanged: (v) => setState(() => _responseRequired = v),
          ),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
            ),
          FilledButton(
            onPressed: _sending ? null : _send,
            child: Text(_sending ? 'Gönderiliyor…' : 'Gönder'),
          ),
        ],
      ),
    );
  }
}

class _Dropdown extends StatelessWidget {
  const _Dropdown({
    required this.label,
    required this.value,
    required this.items,
    required this.onChanged,
  });

  final String label;
  final String value;
  final List<String> items;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) {
    return DropdownButtonFormField<String>(
      value: value, // ignore: deprecated_member_use
      isExpanded: true,
      decoration: InputDecoration(labelText: label, border: const OutlineInputBorder()),
      items: [for (final item in items) DropdownMenuItem(value: item, child: Text(item))],
      onChanged: (v) {
        if (v != null) onChanged(v);
      },
    );
  }
}
