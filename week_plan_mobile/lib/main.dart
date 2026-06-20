import 'package:flutter/material.dart';
import 'package:flutter/cupertino.dart';
import 'package:table_calendar/table_calendar.dart';
import 'package:intl/intl.dart';
import 'package:http/http.dart' as http;
import 'dart:convert';
import 'package:flutter_dotenv/flutter_dotenv.dart';

Future<void> main() async {
  await dotenv.load(fileName: ".env");
  runApp(const WeekPlanApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        colorSchemeSeed: Colors.deepPurple,
        scaffoldBackgroundColor: Colors.grey[100],
      ),
      home: const AssignmentScreen(),
    );
  }
}

class AssignmentScreen extends StatefulWidget {
  const AssignmentScreen({super.key});

  @override
  State<AssignmentScreen> createState() => _AssignmentScreenState();
}

class _AssignmentScreenState extends State<AssignmentScreen> {
  List assignments = [];
  // Your dynamic settings memory
  Map<String, dynamic> userPreferences = {
    "energy_preference": "morning",
    "break_between_sessions_minutes": 0,
    "buffer_days_before_due": 1,
    "auto_breaks": true,
    "auto_break_interval_minutes": 60,
    "auto_break_duration_minutes": 10,
    "allow_overflow": true,
  };
  bool isLoading = false;

  // Translates "1 hr 30 min" into an integer like 90 for the Python backend
  int _parseTimeToMinutes(String timeString) {
    if (timeString == 'Not triaged') return 60; // Default fallback
    int totalMinutes = 0;
    final hrMatch = RegExp(
      r'(\d+)\s*(hr|hour|Hour)',
      caseSensitive: false,
    ).firstMatch(timeString);
    final minMatch = RegExp(
      r'(\d+)\s*(min|Min)',
      caseSensitive: false,
    ).firstMatch(timeString);
    if (hrMatch != null) totalMinutes += int.parse(hrMatch.group(1)!) * 60;
    if (minMatch != null) totalMinutes += int.parse(minMatch.group(1)!);
    return totalMinutes < 15
        ? 15
        : totalMinutes; // Backend requires at least 15 mins
  }

  Future<void> _generateSmartScheduleBackend() async {
    setState(() => isLoading = true);

    try {
      // 1. Format the Canvas assignments into Python "Tasks"
      List<Map<String, dynamic>> tasks = assignments.map((a) {
        return {
          "id":
              a['id'] ??
              a['canvas_id'] ??
              DateTime.now().millisecondsSinceEpoch.toString(),
          "title": a['name'] ?? 'Untitled',
          "task_type": "assignment",
          "course_name": a['course_name'] ?? 'General',
          "due_date":
              a['due_at'] ??
              DateTime.now().add(const Duration(days: 3)).toIso8601String(),
          "estimated_minutes": _parseTimeToMinutes(
            a['time_estimate'] ?? '60 min',
          ),
          "difficulty": 2, // Default medium difficulty
          "max_session_minutes": 60, // Break long tasks into 1-hour chunks
        };
      }).toList();

      // 2. Build the massive ScheduleRequest payload
      final Map<String, dynamic> requestBody = {
        "canvas_domain": "byui.instructure.com",
        "access_token":
            dotenv.env['CANVAS_API_TOKEN'], // <--- Pulls from the hidden file!
        "lookahead_days": 14,
      };

      // 3. Send it to the Python Brain
      print("Sending to Python Scheduler...");
      final response = await http.post(
        Uri.parse('http://10.0.2.2:8000/schedule/generate'),
        headers: {"Content-Type": "application/json"},
        body: json.encode(requestBody),
      );

      if (response.statusCode == 200) {
        final responseData = json.decode(response.body);
        final days = responseData['days'] as List<dynamic>;

        // 4. Update the Calendar UI with the AI's schedule
        _scheduledAssignments.clear();
        for (var dayData in days) {
          DateTime dateKey = DateTime.parse(dayData['date']);

          // FIX: Tell Flutter it is allowed to look at 'break' blocks too!
          List blocks = dayData['blocks']
              .where(
                (b) =>
                    b['block_type'] == 'work' ||
                    b['block_type'] == 'overflow' ||
                    b['block_type'] == 'break', // <--- The missing link
              )
              .toList();

          if (blocks.isNotEmpty) {
            _scheduledAssignments[dateKey] = blocks.map((b) {
              // If it's a break, build a custom UI block for it
              if (b['block_type'] == 'break') {
                return {
                  'name': '☕ Brain Break',
                  'time_estimate': "${b['start_time']} - ${b['end_time']}",
                  'due_at': 'Stretch and hydrate', // Replaces the due date text
                  'course_name': 'Break',
                };
              }

              // Otherwise, hunt down the original Canvas assignment for normal work
              final originalTask = assignments.firstWhere(
                (a) => a['name'] == b['title'],
                orElse: () => {'due_at': 'Unknown'},
              );

              return {
                'name': b['title'],
                'time_estimate': "${b['start_time']} - ${b['end_time']}",
                'due_at': originalTask['due_at'],
                'course_name': b['course_name'] ?? 'Task',
              };
            }).toList();
          }
        }
        setState(() => isLoading = false);
        print("Smart Schedule Built Successfully!");
      } else {
        print("Backend Error: ${response.body}");
        setState(() => isLoading = false);
      }
    } catch (e) {
      print("Network error: $e");
      setState(() => isLoading = false);
    }
  }

  // Calendar State Variables
  DateTime _focusedDay = DateTime.now();
  DateTime? _selectedDay;
  Map<DateTime, List<dynamic>> _scheduledAssignments = {};

  @override
  void initState() {
    super.initState();
    _selectedDay = _focusedDay;
  }

  // =========================================================================
  // THE "PROCRASTINATION BUSTER" ALGORITHM (Mock Frontend Version)
  // Later, your backend LLM will do this and just send the final dates.
  // =========================================================================
  void _buildSmartSchedule() {
    _scheduledAssignments.clear();

    for (var item in assignments) {
      if (item['due_at'] != null) {
        try {
          DateTime actualDueDate = DateTime.parse(item['due_at']);

          // THE MAGIC: Schedule it 2 days BEFORE it is actually due!
          DateTime scheduledDate = actualDueDate.subtract(
            const Duration(days: 2),
          );

          // Normalize the time to midnight so it groups properly on the calendar
          DateTime dateKey = DateTime(
            scheduledDate.year,
            scheduledDate.month,
            scheduledDate.day,
          );

          if (_scheduledAssignments[dateKey] == null) {
            _scheduledAssignments[dateKey] = [];
          }
          _scheduledAssignments[dateKey]!.add(item);
        } catch (e) {
          print("Could not parse date: ${item['due_at']}");
        }
      }
    }
    setState(() {}); // Redraw screen with new schedule
  }

  // Get assignments for a specific day
  List<dynamic> _getAssignmentsForDay(DateTime day) {
    DateTime normalizedDay = DateTime(day.year, day.month, day.day);
    return _scheduledAssignments[normalizedDay] ?? [];
  }

  Future<void> fetchAssignments() async {
    setState(() => isLoading = true);

    try {
      // 1. The Payload (Just like you tested in the browser)
      final Map<String, dynamic> requestBody = {
        "canvas_domain":
            "byui.instructure.com", // Change this to your school's domain
        "access_token": "placeholder",
        "lookahead_days": 14,
      };

      // 2. The POST Request to your new port 8000
      final response = await http.post(
        Uri.parse('http://10.0.2.2:8000/canvas/assignments'),
        headers: {"Content-Type": "application/json"},
        body: json.encode(requestBody),
      );

      if (response.statusCode == 200) {
        // The new FastAPI server returns a direct list
        final List<dynamic> fetchedAssignments = json.decode(response.body);

        setState(() {
          // 3. Map the new Python data labels to what our UI expects
          assignments = fetchedAssignments
              .map(
                (a) => {
                  'id': a['canvas_id'],
                  'name':
                      a['title'], // Python calls it 'title', our UI expects 'name'
                  'due_at': a['due_date'],
                  'course_name': a['course_name'],
                },
              )
              .toList();

          isLoading = false;
        });

        if (assignments.isNotEmpty && mounted) {
          _startTriageFlow();
        }
      } else {
        print("Server Error: ${response.statusCode}");
        setState(() => isLoading = false);
      }
    } catch (e) {
      print("Network error: $e");
      setState(() => isLoading = false);
    }
  }

  void _startTriageFlow() {
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (BuildContext context) {
        return TriageWizard(
          assignments: assignments,
          onComplete: (updatedAssignments) {
            setState(() {
              assignments = updatedAssignments;
              _generateSmartScheduleBackend();
            });
          },
        );
      },
    );
  }

  String _calculateDailyWorkload(List<dynamic> dailyTasks) {
    int totalMinutes = 0;

    for (var item in dailyTasks) {
      final estimate = item['time_estimate'] ?? '';
      if (estimate == 'Not triaged') continue;

      final hrMatch = RegExp(
        r'(\d+)\s*(hr|hour|Hour)',
        caseSensitive: false,
      ).firstMatch(estimate);
      final minMatch = RegExp(
        r'(\d+)\s*(min|Min)',
        caseSensitive: false,
      ).firstMatch(estimate);

      if (hrMatch != null) totalMinutes += int.parse(hrMatch.group(1)!) * 60;
      if (minMatch != null) totalMinutes += int.parse(minMatch.group(1)!);
    }

    if (totalMinutes == 0) return "Free Day!";
    final hours = totalMinutes ~/ 60;
    final mins = totalMinutes % 60;

    if (hours > 0 && mins > 0) return "$hours hr $mins min";
    if (hours > 0) return "$hours hr";
    return "$mins min";
  }

  @override
  Widget build(BuildContext context) {
    final dailyTasks = _selectedDay != null
        ? _getAssignmentsForDay(_selectedDay!)
        : [];

    return Scaffold(
      appBar: AppBar(
        title: const Text(
          "Weekly Canvas Plan",
          style: TextStyle(fontWeight: FontWeight.bold),
        ),
        centerTitle: true,
        actions: [
          IconButton(
            icon: const Icon(Icons.tune),
            onPressed: () async {
              // Open the Settings Screen and wait for the user to save
              final updatedPrefs = await Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (context) =>
                      SettingsScreen(currentPrefs: userPreferences),
                ),
              );
              // If they saved new settings, update our memory!
              if (updatedPrefs != null) {
                setState(() {
                  userPreferences = updatedPrefs;
                });
              }
            },
          ),
        ],
      ),
      body: Column(
        children: [
          // THE CALENDAR WIDGET
          Container(
            color: Colors.white,
            child: TableCalendar(
              firstDay: DateTime.utc(2023, 1, 1),
              lastDay: DateTime.utc(2030, 12, 31),
              focusedDay: _focusedDay,
              selectedDayPredicate: (day) => isSameDay(_selectedDay, day),
              calendarFormat:
                  CalendarFormat.week, // Force it to a single week view!
              startingDayOfWeek: StartingDayOfWeek.monday,
              eventLoader:
                  _getAssignmentsForDay, // Shows dots on days with work
              onDaySelected: (selectedDay, focusedDay) {
                setState(() {
                  _selectedDay = selectedDay;
                  _focusedDay = focusedDay;
                });
              },
              calendarStyle: CalendarStyle(
                selectedDecoration: BoxDecoration(
                  color: Colors.deepPurple,
                  shape: BoxShape.circle,
                ),
                todayDecoration: BoxDecoration(
                  color: Colors.deepPurple.shade200,
                  shape: BoxShape.circle,
                ),
                markerDecoration: const BoxDecoration(
                  color: Colors.deepOrange,
                  shape: BoxShape.circle,
                ),
              ),
            ),
          ),

          if (isLoading)
            const Expanded(child: Center(child: CircularProgressIndicator()))
          else if (assignments.isEmpty)
            const Expanded(
              child: Center(
                child: Text("Hit the download button to grab your week!"),
              ),
            )
          else ...[
            // DAILY DASHBOARD
            Container(
              width: double.infinity,
              margin: const EdgeInsets.all(16),
              padding: const EdgeInsets.all(20),
              decoration: BoxDecoration(
                gradient: LinearGradient(
                  colors: [
                    Colors.deepPurple.shade700,
                    Colors.deepPurple.shade400,
                  ],
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                ),
                borderRadius: BorderRadius.circular(20),
              ),
              child: Column(
                children: [
                  Text(
                    _selectedDay != null
                        ? DateFormat(
                            'EEEE, MMMM d',
                          ).format(_selectedDay!).toUpperCase()
                        : "TODAY's WORKLOAD",
                    style: const TextStyle(
                      color: Colors.white70,
                      fontSize: 12,
                      letterSpacing: 1.5,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    _calculateDailyWorkload(dailyTasks),
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 32,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ],
              ),
            ),

            // ASSIGNMENT LIST FOR THE SELECTED DAY
            Expanded(
              child: dailyTasks.isEmpty
                  ? Center(
                      child: Text(
                        "Nothing scheduled for this day.",
                        style: TextStyle(color: Colors.grey.shade600),
                      ),
                    )
                  : ListView.builder(
                      padding: const EdgeInsets.symmetric(horizontal: 16),
                      itemCount: dailyTasks.length,
                      itemBuilder: (context, index) {
                        final item = dailyTasks[index];
                        final timeEstimate =
                            item['time_estimate'] ?? 'Not triaged';

                        // Parse original due date to show the user
                        String dueText = 'Unknown';
                        if (item['due_at'] != null) {
                          try {
                            DateTime dueDate = DateTime.parse(item['due_at']);
                            dueText = DateFormat(
                              'MMM d, h:mm a',
                            ).format(dueDate);
                          } catch (e) {}
                        }

                        return Card(
                          elevation: 2,
                          margin: const EdgeInsets.only(bottom: 12),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(16),
                          ),
                          child: ListTile(
                            contentPadding: const EdgeInsets.all(12),
                            title: Text(
                              item['name'] ?? 'No Title',
                              style: const TextStyle(
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                            subtitle: Padding(
                              padding: const EdgeInsets.only(top: 8.0),
                              child: Text(
                                "Actually Due: $dueText",
                                style: TextStyle(color: Colors.red.shade700),
                              ),
                            ),
                            trailing: Container(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 12,
                                vertical: 8,
                              ),
                              decoration: BoxDecoration(
                                color: Colors.deepPurple.shade50,
                                borderRadius: BorderRadius.circular(20),
                              ),
                              child: Text(
                                timeEstimate,
                                style: TextStyle(
                                  color: Colors.deepPurple.shade700,
                                  fontWeight: FontWeight.bold,
                                ),
                              ),
                            ),
                          ),
                        );
                      },
                    ),
            ),
          ],
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: fetchAssignments,
        icon: const Icon(Icons.cloud_sync),
        label: const Text("Fetch Canvas"),
      ),
    );
  }
}

// =========================================================================
// THE TRIAGE WIZARD POPUP
// =========================================================================
class TriageWizard extends StatefulWidget {
  final List assignments;
  final Function(List) onComplete;

  const TriageWizard({
    super.key,
    required this.assignments,
    required this.onComplete,
  });

  @override
  State<TriageWizard> createState() => _TriageWizardState();
}

class _TriageWizardState extends State<TriageWizard> {
  int currentIndex = 0;
  late List localAssignments;

  @override
  void initState() {
    super.initState();
    localAssignments = List.from(widget.assignments);
  }

  void _saveTimeAndMoveOn(String timeLabel) {
    localAssignments[currentIndex]['time_estimate'] = timeLabel;

    if (currentIndex < localAssignments.length - 1) {
      setState(() {
        currentIndex++;
      });
    } else {
      widget.onComplete(localAssignments);
      Navigator.of(context).pop();
    }
  }

  void _showCustomTimePicker() {
    Duration selectedDuration = const Duration(hours: 1);

    showModalBottomSheet(
      context: context,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (BuildContext builder) {
        return Container(
          height: 300,
          padding: const EdgeInsets.only(top: 8),
          decoration: const BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
          ),
          child: Column(
            children: [
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    TextButton(
                      onPressed: () => Navigator.pop(context),
                      child: const Text(
                        "Cancel",
                        style: TextStyle(color: Colors.grey, fontSize: 16),
                      ),
                    ),
                    TextButton(
                      onPressed: () {
                        Navigator.pop(context);

                        String formattedTime = "";
                        if (selectedDuration.inHours > 0)
                          formattedTime += "${selectedDuration.inHours} hr ";
                        if (selectedDuration.inMinutes % 60 > 0)
                          formattedTime +=
                              "${selectedDuration.inMinutes % 60} min";
                        if (formattedTime.isEmpty) formattedTime = "0 min";

                        _saveTimeAndMoveOn(formattedTime.trim());
                      },
                      child: const Text(
                        "Done",
                        style: TextStyle(
                          fontWeight: FontWeight.bold,
                          fontSize: 16,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              const Divider(),
              Expanded(
                child: CupertinoTimerPicker(
                  mode: CupertinoTimerPickerMode.hm,
                  initialTimerDuration: selectedDuration,
                  onTimerDurationChanged: (Duration newDuration) =>
                      selectedDuration = newDuration,
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final currentItem = localAssignments[currentIndex];
    final progress = (currentIndex + 1) / localAssignments.length;

    return Dialog(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
      child: Padding(
        padding: const EdgeInsets.all(24.0),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              "Triage: ${currentIndex + 1} of ${localAssignments.length}",
              textAlign: TextAlign.center,
              style: const TextStyle(
                color: Colors.grey,
                fontWeight: FontWeight.bold,
              ),
            ),
            const SizedBox(height: 8),
            LinearProgressIndicator(
              value: progress,
              borderRadius: BorderRadius.circular(10),
            ),
            const SizedBox(height: 24),

            const Text(
              "How long will this take?",
              style: TextStyle(fontSize: 16),
            ),
            const SizedBox(height: 12),
            Text(
              currentItem['name'] ?? 'Unknown Assignment',
              style: const TextStyle(fontSize: 22, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 8),

            // Format Due Date for Triage
            Builder(
              builder: (context) {
                String triageDueText = 'Unknown';
                if (currentItem['due_at'] != null) {
                  try {
                    DateTime d = DateTime.parse(currentItem['due_at']);
                    triageDueText = DateFormat('MMM d, h:mm a').format(d);
                  } catch (e) {}
                }
                return Text(
                  "Due: $triageDueText",
                  style: TextStyle(
                    color: Colors.red.shade700,
                    fontWeight: FontWeight.w500,
                  ),
                );
              },
            ),

            const SizedBox(height: 32),

            Wrap(
              spacing: 10,
              runSpacing: 10,
              alignment: WrapAlignment.center,
              children: [
                _buildTimeButton("15 Min"),
                _buildTimeButton("30 Min"),
                _buildTimeButton("1 hr"),
              ],
            ),
            const SizedBox(height: 20),
            OutlinedButton.icon(
              style: OutlinedButton.styleFrom(
                padding: const EdgeInsets.symmetric(vertical: 14),
                side: BorderSide(color: Colors.deepPurple.shade200),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12),
                ),
              ),
              icon: const Icon(Icons.tune),
              label: const Text("Need more time? (Custom)"),
              onPressed: _showCustomTimePicker,
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildTimeButton(String label) {
    return ActionChip(
      label: Text(
        label,
        style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
      ),
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      backgroundColor: Colors.deepPurple.shade50,
      side: BorderSide.none,
      onPressed: () => _saveTimeAndMoveOn(label),
    );
  }
}

// =========================================================================
// THE SETTINGS / PREFERENCES SCREEN
// =========================================================================
class SettingsScreen extends StatefulWidget {
  final Map<String, dynamic> currentPrefs;

  const SettingsScreen({super.key, required this.currentPrefs});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  late Map<String, dynamic> localPrefs;

  @override
  void initState() {
    super.initState();
    // Make a copy of the current settings to edit
    localPrefs = Map<String, dynamic>.from(widget.currentPrefs);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text("Algorithm Preferences"),
        backgroundColor: Colors.deepPurple.shade50,
      ),
      body: ListView(
        padding: const EdgeInsets.all(16.0),
        children: [
          const Padding(
            padding: EdgeInsets.only(bottom: 8.0, left: 4),
            child: Text(
              "ENERGY & FOCUS",
              style: TextStyle(
                color: Colors.deepPurple,
                fontWeight: FontWeight.bold,
              ),
            ),
          ),
          Card(
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(16),
            ),
            child: Padding(
              padding: const EdgeInsets.all(16.0),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    "When do you focus best?",
                    style: TextStyle(fontSize: 16),
                  ),
                  const SizedBox(height: 8),
                  DropdownButtonFormField<String>(
                    value: localPrefs['energy_preference'],
                    decoration: InputDecoration(
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12),
                      ),
                      contentPadding: const EdgeInsets.symmetric(
                        horizontal: 16,
                      ),
                    ),
                    items: const [
                      DropdownMenuItem(
                        value: "morning",
                        child: Text("Morning (6am - 12pm)"),
                      ),
                      DropdownMenuItem(
                        value: "midday",
                        child: Text("Midday (12pm - 5pm)"),
                      ),
                      DropdownMenuItem(
                        value: "evening",
                        child: Text("Evening (5pm - 11pm)"),
                      ),
                      DropdownMenuItem(
                        value: "no_preference",
                        child: Text("No Preference"),
                      ),
                    ],
                    onChanged: (val) =>
                        setState(() => localPrefs['energy_preference'] = val!),
                  ),
                ],
              ),
            ),
          ),

          const SizedBox(height: 24),
          const Padding(
            padding: EdgeInsets.only(bottom: 8.0, left: 4),
            child: Text(
              "SCHEDULING RULES",
              style: TextStyle(
                color: Colors.deepPurple,
                fontWeight: FontWeight.bold,
              ),
            ),
          ),
          Card(
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(16),
            ),
            child: Column(
              children: [
                ListTile(
                  title: const Text("Buffer Days"),
                  subtitle: const Text(
                    "How many days before the due date should the AI schedule the work?",
                  ),
                  trailing: Text(
                    "${localPrefs['buffer_days_before_due']} Days",
                    style: const TextStyle(
                      fontWeight: FontWeight.bold,
                      fontSize: 16,
                    ),
                  ),
                ),
                Slider(
                  value: localPrefs['buffer_days_before_due'].toDouble(),
                  min: 0,
                  max: 3,
                  divisions: 3,
                  activeColor: Colors.deepPurple,
                  onChanged: (val) => setState(
                    () => localPrefs['buffer_days_before_due'] = val.toInt(),
                  ),
                ),
                const Divider(height: 1),
                SwitchListTile(
                  title: const Text("Auto-Break System"),
                  subtitle: const Text(
                    "Insert a 10-min break every hour of studying.",
                  ),
                  activeColor: Colors.deepPurple,
                  value: localPrefs['auto_breaks'],
                  onChanged: (val) =>
                      setState(() => localPrefs['auto_breaks'] = val),
                ),
                const Divider(height: 1),
                SwitchListTile(
                  title: const Text("Allow Overflow"),
                  subtitle: const Text(
                    "If your week is completely full, schedule tasks outside your normal hours to ensure they get done.",
                  ),
                  activeColor: Colors.deepPurple,
                  value: localPrefs['allow_overflow'],
                  onChanged: (val) =>
                      setState(() => localPrefs['allow_overflow'] = val),
                ),
              ],
            ),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () {
          // Send the new settings back to the main screen
          Navigator.pop(context, localPrefs);
        },
        icon: const Icon(Icons.save),
        label: const Text("Save & Apply"),
      ),
    );
  }
}
